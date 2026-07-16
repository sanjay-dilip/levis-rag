"""Run the 60-question eval set through both Gemini Flash and Groq/Llama 3.3 70B
tier-tagging paths, holding retrieval constant, for issue #25's model comparison.

Retrieval (retrieve()) is called once per question; the same top-10 chunks
are then passed to both tagging paths so only the tagging model differs.
Results (not just scores) are written incrementally to
data/tier_comparison_raw.json so a crash or Ctrl-C loses at most one
question's work, and re-running resumes from the last completed question.

IMPORTANT: this script does not alter tier_tagger.py or app/routers/query.py.
It is a standalone research artifact for issue #25, not a production path.
"""

import argparse
import json
import logging
import os
import re
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

from dotenv import load_dotenv
from google import genai

from retrieve import build_retriever
from tier_tagger import tag_claims
from tier_tagger_groq import tag_claims_groq

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

EVAL_SET_PATH = Path("data/eval_set.json")
RAW_RESULTS_PATH = Path("data/tier_comparison_raw.json")
TOP_K = 10

# GROQ_TPM_BUDGET / GROQ_MIN_REMAINING_TOKENS: the feasibility check found a
# single tier-tagging call at this prompt size consumes ~9,400 of the
# 12,000 TPM budget - the free tier supports roughly one call per minute,
# not a burst. GROQ_FALLBACK_DELAY_SECONDS is used only if the response
# doesn't carry rate-limit headers to compute a dynamic wait from.
GROQ_MIN_REMAINING_TOKENS = 9500
GROQ_FALLBACK_DELAY_SECONDS = 70.0
GEMINI_DELAY_SECONDS = 2.0

_RESET_PATTERN = re.compile(r"(?:(\d+)m)?([\d.]+)s")


def _parse_reset_duration(reset_str: str) -> float:
    """Parse Groq's 'x-ratelimit-reset-tokens' style duration (e.g. '1m26.4s') to seconds."""
    match = _RESET_PATTERN.match(reset_str)
    if not match:
        return GROQ_FALLBACK_DELAY_SECONDS
    minutes = float(match.group(1)) if match.group(1) else 0.0
    seconds = float(match.group(2))
    return minutes * 60 + seconds


def _groq_wait_seconds(headers: dict | None, success: bool) -> float:
    """Compute how long to sleep before the next Groq call, from rate-limit headers.

    Only trusts headers for dynamic pacing when the call that produced them
    succeeded. A failed (e.g. 429) response can carry headers claiming a
    fully refreshed token window even though the call itself failed -
    trusting those would compute a zero-second wait and trigger a
    rate-limit cascade from rapid-fire retries (observed in practice,
    issue #25's first run attempt).
    """
    if not success:
        return GROQ_FALLBACK_DELAY_SECONDS
    if not headers:
        return GROQ_FALLBACK_DELAY_SECONDS
    try:
        remaining_tokens = int(headers.get("x-ratelimit-remaining-tokens", 0))
    except (TypeError, ValueError):
        return GROQ_FALLBACK_DELAY_SECONDS
    if remaining_tokens >= GROQ_MIN_REMAINING_TOKENS:
        return 0.0
    reset_str = headers.get("x-ratelimit-reset-tokens")
    if not reset_str:
        return GROQ_FALLBACK_DELAY_SECONDS
    return _parse_reset_duration(reset_str) + 2.0  # small safety buffer


def _load_existing_results() -> dict:
    if RAW_RESULTS_PATH.exists():
        return json.loads(RAW_RESULTS_PATH.read_text(encoding="utf-8"))
    return {}


def _save_results(results: dict) -> None:
    RAW_RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")


def _is_parse_failure(result: dict) -> bool:
    for claim in result.get("claims", []):
        text = claim.get("claim_text", "")
        if text.startswith("Parse failure:") or text.startswith("Runner-level failure:"):
            return True
    return False


_GEMINI_RETRY_DELAY_PATTERN = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)

GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_FALLBACK_SECONDS = 30.0


def _gemini_retry_delay(exc_text: str) -> float:
    """Parse Gemini's suggested 'Please retry in Ns' delay, or a fallback."""
    match = _GEMINI_RETRY_DELAY_PATTERN.search(exc_text)
    if match:
        return float(match.group(1)) + 2.0  # small safety buffer
    return GEMINI_RETRY_FALLBACK_SECONDS


def tag_claims_gemini_with_retry(question: str, hits: list[dict], client) -> dict:
    """Call tag_claims with retry-with-backoff on a RESOURCE_EXHAUSTED failure.

    Despite the free-tier error body naming its quotaId
    'GenerateRequestsPerDayPerProjectPerModel-FreeTier', empirically (issue
    #25's first run attempt) this recovers within tens of seconds, not 24
    hours - the label is misleading. A short real backoff, honoring the
    server's own suggested retry delay when present, resolves it far more
    often than not.
    """
    result = tag_claims(question, hits, client)
    for _ in range(GEMINI_MAX_RETRIES):
        if not _is_parse_failure(result):
            return result
        claim_text = result["claims"][0]["claim_text"]
        if "RESOURCE_EXHAUSTED" not in claim_text:
            return result  # a different kind of failure - retrying won't help
        delay = _gemini_retry_delay(claim_text)
        print(f"  gemini RESOURCE_EXHAUSTED, retrying in {delay:.1f}s...")
        time.sleep(delay)
        result = tag_claims(question, hits, client)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--estimate-only",
        action="store_true",
        help="Print the wall-clock time estimate and exit without calling any API.",
    )
    parser.add_argument(
        "--max-total",
        type=int,
        default=None,
        help=(
            "Stop once this many questions have a genuine result on both sides "
            "(counting ones already done). Used to split the 60-question set into "
            "resumable phases across sessions, e.g. --max-total 30 for a first "
            "phase, then run again later (with no --max-total, or --max-total 60) "
            "to cover the rest."
        ),
    )
    args = parser.parse_args()

    eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    existing = _load_existing_results()
    # Only skip a question if BOTH sides produced a genuine result. A
    # question where either side hit a parse failure (e.g. a transient
    # rate-limit 429) stays in the queue so a re-run retries it, rather
    # than permanently recording the failure as "done".
    done_ids = {
        qid
        for qid, record in existing.items()
        if not _is_parse_failure(record["gemini"]) and not _is_parse_failure(record["groq"])
    }
    remaining = [q for q in eval_set if q["id"] not in done_ids]
    if args.max_total is not None:
        n_needed = max(0, args.max_total - len(done_ids))
        remaining = remaining[:n_needed]

    est_seconds = len(remaining) * (GROQ_FALLBACK_DELAY_SECONDS + GEMINI_DELAY_SECONDS + 2.0)
    print(
        f"{len(eval_set)} total questions, {len(done_ids)} genuinely completed "
        f"(both models succeeded), {len(existing) - len(done_ids)} recorded as a "
        f"parse failure on at least one side (will be retried)."
    )
    if args.max_total is not None:
        print(
            f"--max-total {args.max_total}: will attempt {len(remaining)} more "
            f"question(s) this run to reach {args.max_total} genuinely completed."
        )
    else:
        print(f"{len(remaining)} remaining toward the full 60.")
    print(
        f"Estimated wall-clock time for remaining questions: "
        f"~{est_seconds / 60:.1f} minutes (~{GROQ_FALLBACK_DELAY_SECONDS:.0f}s/question, "
        f"paced by Groq's free-tier TPM budget)."
    )
    if args.estimate_only or not remaining:
        return

    load_dotenv()
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not gemini_api_key:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")
    if not groq_api_key:
        raise EnvironmentError("GROQ_API_KEY not set in .env")

    gemini_client = genai.Client(api_key=gemini_api_key)
    retriever = build_retriever()

    start_time = time.monotonic()
    consecutive_groq_failures = 0
    consecutive_gemini_failures = 0
    for i, q in enumerate(remaining, start=1):
        qid = q["id"]
        question = q["question"]
        print(f"\n[{i}/{len(remaining)}] {qid}: {question}")

        hits = retriever.retrieve(question, top_k=TOP_K)
        chunk_ids = [h["id"] for h in hits]

        try:
            gemini_result = tag_claims_gemini_with_retry(question, hits, gemini_client)
        except Exception as exc:  # tag_claims already catches internally; belt-and-suspenders
            gemini_result = {
                "answer": str(exc),
                "claims": [
                    {
                        "claim_text": f"Runner-level failure: {exc}",
                        "tier": "Model-inference",
                        "supporting_chunk_id": -1,
                        "fiscal_year": None,
                    }
                ],
            }
        time.sleep(GEMINI_DELAY_SECONDS)

        if _is_parse_failure(gemini_result):
            consecutive_gemini_failures += 1
        else:
            consecutive_gemini_failures = 0

        if consecutive_gemini_failures >= 5:
            print(
                f"\n{consecutive_gemini_failures} consecutive Gemini failures even after "
                "per-call retries - stopping rather than burning further failed calls. "
                "This question was NOT saved and will be retried from scratch on the "
                "next run."
            )
            break

        groq_result, groq_headers, groq_success = tag_claims_groq(question, hits, groq_api_key)
        if groq_success:
            consecutive_groq_failures = 0
        else:
            consecutive_groq_failures += 1

        results = _load_existing_results()
        results[qid] = {
            "question": question,
            "expected_tier": q["expected_tier"],
            "question_type": q["question_type"],
            "retrieved_chunk_ids": chunk_ids,
            "gemini": gemini_result,
            "groq": groq_result,
            "groq_rate_limit_headers": groq_headers,
        }
        _save_results(results)
        print(f"  gemini tiers: {[c.get('tier') for c in gemini_result.get('claims', [])]}")
        print(f"  groq tiers:   {[c.get('tier') for c in groq_result.get('claims', [])]}")

        if consecutive_groq_failures >= 3:
            print(
                f"\n{consecutive_groq_failures} consecutive Groq failures - stopping rather "
                "than burning further failed calls. This question's Groq result was saved "
                "as a parse failure and will be retried on the next run (gemini side may "
                "still be genuine for this question). Re-run after investigating/waiting."
            )
            break

        wait = _groq_wait_seconds(groq_headers, groq_success)
        if i < len(remaining) and wait > 0:
            print(f"  waiting {wait:.1f}s for Groq TPM budget to refill...")
            time.sleep(wait)

    elapsed = time.monotonic() - start_time
    print(f"\nDone (this invocation). {i} questions attempted in {elapsed / 60:.1f} minutes.")
    print(f"Raw results written to {RAW_RESULTS_PATH}")


if __name__ == "__main__":
    main()
