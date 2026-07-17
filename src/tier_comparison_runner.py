"""Run the 60-question eval set through both Gemini Flash and Groq/Llama 3.3 70B
tier-tagging paths, holding retrieval constant, for issue #25's model comparison.

Retrieval (retrieve()) is called once per question; the same top-10 chunks
are then passed to both tagging paths so only the tagging model differs.
Results (not just scores) are written incrementally to
data/tier_comparison_raw.json so a crash or Ctrl-C loses at most one
question's work, and re-running resumes from the last completed question.

IMPORTANT: this script does not alter tier_tagger.py or app/routers/query.py.
It is a standalone research artifact (originally #25, continued under #31
with a dedicated key/project), not a production path. It reads
GEMINI_API_KEY_II specifically - a second, genuinely separate Google AI
Studio project's key - not GEMINI_API_KEY (which stays exclusively
production's, permanently, so this script's daily quota use never
competes with the live /query path's).

On a Gemini RESOURCE_EXHAUSTED (daily quota) response, this script stops
immediately rather than retrying: that quota (
GenerateRequestsPerDayPerProjectPerModel-FreeTier, 20/day) resets once a
day, not within a session, so retrying against it only spends more of an
already-exhausted budget (confirmed in practice - issue #28's session
spent 3 extra retries on one already-exhausted question and still failed).
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


def _is_resource_exhausted(result: dict) -> bool:
    """True if a Gemini tagging result is a RESOURCE_EXHAUSTED (daily quota) failure.

    Distinct from _is_parse_failure: a parse failure can be any kind of
    error (malformed model output, a transient 5xx, etc.); this checks
    specifically for the daily-quota case, which is the one that must not
    be retried (see module docstring).
    """
    for claim in result.get("claims", []):
        if "RESOURCE_EXHAUSTED" in claim.get("claim_text", ""):
            return True
    return False


def tag_claims_gemini_once(question: str, hits: list[dict], client) -> dict:
    """Single Gemini tagging call, no retry.

    A RESOURCE_EXHAUSTED (daily quota) failure is a hard stop handled by
    the caller, not retried here - see module docstring for why retrying
    it is pure waste. Other failure types (malformed output, transient
    errors) are returned as-is; tag_claims already catches and reports
    those internally as a "Parse failure:"-prefixed claim.
    """
    try:
        return tag_claims(question, hits, client)
    except Exception as exc:  # tag_claims already catches internally; belt-and-suspenders
        return {
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


def _done_ids(existing: dict) -> set[str]:
    """Question ids with a genuine (non-parse-failure) result on both sides.

    A question with a parse failure on either side is deliberately
    excluded - it stays in the queue so a re-run retries it, rather than
    the failure being silently treated as permanent.
    """
    return {
        qid
        for qid, record in existing.items()
        if not _is_parse_failure(record["gemini"]) and not _is_parse_failure(record["groq"])
    }


def _compute_remaining(eval_set: list[dict], existing: dict, max_total: int | None) -> list[dict]:
    """Questions still needing a genuine result, in eval_set order.

    This is the actual resumability check (confirmed by direct test, not
    assumed): a question already done on both sides is skipped entirely,
    so a re-run never re-calls Gemini/Groq for it.
    """
    done_ids = _done_ids(existing)
    remaining = [q for q in eval_set if q["id"] not in done_ids]
    if max_total is not None:
        n_needed = max(0, max_total - len(done_ids))
        remaining = remaining[:n_needed]
    return remaining


def _process_question(
    q: dict, gemini_client, groq_api_key: str, retriever
) -> tuple[dict | None, bool]:
    """Run one question through both models.

    Returns (record, gemini_exhausted). If Gemini hits RESOURCE_EXHAUSTED,
    returns (None, True) immediately - Groq is never called for this
    question (no point spending its budget on a question that can't be
    completed today anyway) and nothing is saved, so the next run retries
    it from scratch rather than persisting a wasted/incomplete attempt.
    """
    question = q["question"]
    hits = retriever.retrieve(question, top_k=TOP_K)
    chunk_ids = [h["id"] for h in hits]

    gemini_result = tag_claims_gemini_once(question, hits, gemini_client)
    time.sleep(GEMINI_DELAY_SECONDS)
    if _is_resource_exhausted(gemini_result):
        return None, True

    groq_result, groq_headers, _groq_success = tag_claims_groq(question, hits, groq_api_key)
    record = {
        "question": question,
        "expected_tier": q["expected_tier"],
        "question_type": q["question_type"],
        "retrieved_chunk_ids": chunk_ids,
        "gemini": gemini_result,
        "groq": groq_result,
        "groq_rate_limit_headers": groq_headers,
    }
    return record, False


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
    done_count = len(_done_ids(existing))
    remaining = _compute_remaining(eval_set, existing, args.max_total)

    est_seconds = len(remaining) * (GROQ_FALLBACK_DELAY_SECONDS + GEMINI_DELAY_SECONDS + 2.0)
    print(
        f"{len(eval_set)} total questions, {done_count} genuinely completed "
        f"(both models succeeded), {len(existing) - done_count} recorded as a "
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
    # GEMINI_API_KEY_II deliberately, not GEMINI_API_KEY: a second, genuinely
    # separate Google AI Studio project's key, dedicated to this script only,
    # so its daily quota use never competes with production's (see module
    # docstring). GEMINI_API_KEY is production's alone and is never read here.
    gemini_api_key = os.getenv("GEMINI_API_KEY_II")
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not gemini_api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY_II not set in .env - this script uses a dedicated "
            "second Gemini project's key, not GEMINI_API_KEY (production's)."
        )
    if not groq_api_key:
        raise EnvironmentError("GROQ_API_KEY not set in .env")

    gemini_client = genai.Client(api_key=gemini_api_key)
    retriever = build_retriever()

    start_time = time.monotonic()
    consecutive_groq_failures = 0
    consecutive_gemini_failures = 0
    for i, q in enumerate(remaining, start=1):
        qid = q["id"]
        print(f"\n[{i}/{len(remaining)}] {qid}: {q['question']}")

        record, gemini_exhausted = _process_question(q, gemini_client, groq_api_key, retriever)

        if gemini_exhausted:
            print(
                f"\nGemini RESOURCE_EXHAUSTED (daily quota) at {qid} - stopping "
                "immediately, no retry (retrying a daily quota only spends more "
                "of an already-exhausted budget). This question was NOT saved "
                "and will be retried from scratch on the next run, once the "
                "daily quota has actually reset."
            )
            break

        # Non-quota Gemini failures (malformed output, transient errors) are
        # still saved (so Groq's genuine result for this question isn't
        # thrown away) but tracked as a distinct, non-fatal safeguard from
        # the quota hard-stop above.
        if _is_parse_failure(record["gemini"]):
            consecutive_gemini_failures += 1
        else:
            consecutive_gemini_failures = 0
        if consecutive_gemini_failures >= 5:
            print(
                f"\n{consecutive_gemini_failures} consecutive non-quota Gemini failures - "
                "stopping rather than burning further failed calls."
            )
            results = _load_existing_results()
            results[qid] = record
            _save_results(results)
            break

        groq_success = not _is_parse_failure(record["groq"])
        if groq_success:
            consecutive_groq_failures = 0
        else:
            consecutive_groq_failures += 1

        results = _load_existing_results()
        results[qid] = record
        _save_results(results)
        print(f"  gemini tiers: {[c.get('tier') for c in record['gemini'].get('claims', [])]}")
        print(f"  groq tiers:   {[c.get('tier') for c in record['groq'].get('claims', [])]}")

        if consecutive_groq_failures >= 3:
            print(
                f"\n{consecutive_groq_failures} consecutive Groq failures - stopping rather "
                "than burning further failed calls. This question's Groq result was saved "
                "as a parse failure and will be retried on the next run (gemini side may "
                "still be genuine for this question). Re-run after investigating/waiting."
            )
            break

        wait = _groq_wait_seconds(record["groq_rate_limit_headers"], groq_success)
        if i < len(remaining) and wait > 0:
            print(f"  waiting {wait:.1f}s for Groq TPM budget to refill...")
            time.sleep(wait)

    elapsed = time.monotonic() - start_time
    print(f"\nDone (this invocation). {i} questions attempted in {elapsed / 60:.1f} minutes.")
    print(f"Raw results written to {RAW_RESULTS_PATH}")


if __name__ == "__main__":
    main()
