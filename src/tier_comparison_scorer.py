"""Score data/tier_comparison_raw.json: confusion matrices, per-class precision/
recall, and a hallucination-rate proxy for both the Gemini and Groq tagging
paths (issue #25).

IMPORTANT CONFOUND, restated here so it travels with the numbers: Gemini
uses schema-enforced structured output (response_schema); Groq/Llama 3.3
70B only gets json_object mode plus the schema serialized into the prompt
as text, with no mechanical enforcement (confirmed in the pre-T12
feasibility check). Any quality gap below is a bundled measurement of
model quality AND structured-output reliability, not model quality alone.

Scoring conventions (see report for full rationale):
- A question's "primary predicted tier" is the tier of the LAST claim in
  its claims list. Multi-claim answers typically state supporting facts
  first and the direct answer/conclusion last; a first-claim or majority-
  vote convention would misclassify inference questions where several
  Verified-from-filing supporting claims precede one concluding
  Model-inference claim.
- expected_tier == "Not-in-corpus" (5 out_of_scope questions) is not one
  of TIER_SCHEMA's four enum values - the schema's own system prompt
  defines the correct decline behavior as a single Model-inference claim
  explaining the gap. The raw 5-class confusion matrix keeps
  "Not-in-corpus" as its own expected-side row (never a predicted-side
  column, since the schema can't produce it) for full transparency. The
  collapsed 4-class precision/recall table additionally merges
  expected="Not-in-corpus" into expected="Model-inference" (documented
  inline) so a standard per-class precision/recall table can be computed;
  this merge is a scoring convention, not a claim that the two mean the
  same thing.
- Hallucination rate is an AUTOMATED PROXY, not human or LLM-judged fact-
  checking: a claim with supporting_chunk_id != -1 is flagged if (a) the
  cited chunk id was not even among the retrieved chunks shown to the
  model, or (b) the claim contains a numeric figure that does not appear
  in the cited chunk's text, or (c) for purely non-numeric claims, fewer
  than 20% of the claim's significant words appear in the cited chunk's
  text. Method (c) is a weak signal and is reported separately from (a)/
  (b) so the report doesn't overstate its confidence.
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

RAW_RESULTS_PATH = Path("data/tier_comparison_raw.json")
CHUNKS_PATH = Path("data/chunks_v2.json")
OUTPUT_PATH = Path("data/tier_comparison_scores.json")

SCHEMA_TIERS = [
    "Verified-from-filing",
    "Management-qualitative-statement",
    "Third-party-benchmark",
    "Model-inference",
]

_NUMERIC_PATTERN = re.compile(r"\$?[\d][\d,]*\.?\d*\s?(?:%|million|billion|thousand)?", re.IGNORECASE)
_STOPWORDS = {
    "the", "and", "for", "was", "were", "with", "that", "this", "from",
    "have", "has", "had", "levi", "levis", "which", "their", "there",
    "compared", "including", "than", "these", "those", "into", "also",
    "about", "over", "under", "such", "will", "would", "could", "should",
}


def _normalize_number(token: str) -> str:
    """Strip formatting so '$3,076.8 million' and '3076.8' compare equal."""
    return re.sub(r"[,$\s]", "", token).lower()


def _extract_numbers(text: str) -> list[str]:
    raw = _NUMERIC_PATTERN.findall(text)
    normalized = [_normalize_number(t) for t in raw]
    # Drop bare small integers (years, list indices, chunk ids already
    # excluded) that are too generic to be meaningful grounding signals.
    return [n for n in normalized if len(re.sub(r"[^\d]", "", n)) >= 2]


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]{5,}", text.lower())
    return {w for w in words if w not in _STOPWORDS}


def _load_chunk_text_lookup() -> dict[int, str]:
    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    return {c["id"]: c["text"] for c in chunks}


def check_claim_grounding(
    claim: dict, retrieved_chunk_ids: list[int], chunk_text_lookup: dict[int, str]
) -> dict | None:
    """Return a hallucination-flag dict if the claim looks unsupported, else None.

    Only evaluates claims with supporting_chunk_id != -1, per the task's
    hallucination definition (a Model-inference claim citing -1 is not a
    hallucination candidate by definition).
    """
    chunk_id = claim.get("supporting_chunk_id")
    if chunk_id is None or chunk_id == -1:
        return None

    if chunk_id not in retrieved_chunk_ids:
        return {"method": "chunk_not_retrieved", "chunk_id": chunk_id}

    chunk_text = chunk_text_lookup.get(chunk_id)
    if chunk_text is None:
        return {"method": "chunk_not_found_in_corpus", "chunk_id": chunk_id}

    normalized_chunk = _normalize_number(chunk_text)
    claim_numbers = _extract_numbers(claim.get("claim_text", ""))
    if claim_numbers:
        ungrounded = [n for n in claim_numbers if n not in normalized_chunk]
        if ungrounded and len(ungrounded) == len(claim_numbers):
            return {
                "method": "numeric_grounding",
                "chunk_id": chunk_id,
                "ungrounded_numbers": ungrounded,
            }
        return None

    claim_words = _significant_words(claim.get("claim_text", ""))
    if not claim_words:
        return None
    chunk_words = _significant_words(chunk_text)
    overlap = len(claim_words & chunk_words) / len(claim_words)
    if overlap < 0.20:
        return {"method": "keyword_overlap", "chunk_id": chunk_id, "overlap": round(overlap, 3)}
    return None


def _primary_tier(result: dict) -> str:
    """Tier of the last claim, or a sentinel if the model returned no claims."""
    claims = result.get("claims", [])
    if not claims:
        return "NO_CLAIMS"
    return claims[-1].get("tier", "NO_CLAIMS")


def _is_parse_failure(result: dict) -> bool:
    for claim in result.get("claims", []):
        text = claim.get("claim_text", "")
        if text.startswith("Parse failure:") or text.startswith("Runner-level failure:"):
            return True
    return False


def _precision_recall(expected_labels: list[str], predicted_labels: list[str], classes: list[str]) -> dict:
    metrics = {}
    for cls in classes:
        tp = sum(1 for e, p in zip(expected_labels, predicted_labels) if p == cls and e == cls)
        fp = sum(1 for e, p in zip(expected_labels, predicted_labels) if p == cls and e != cls)
        fn = sum(1 for e, p in zip(expected_labels, predicted_labels) if p != cls and e == cls)
        support = sum(1 for e in expected_labels if e == cls)
        precision = tp / (tp + fp) if (tp + fp) > 0 else None
        recall = tp / (tp + fn) if (tp + fn) > 0 else None
        metrics[cls] = {
            "precision": precision,
            "recall": recall,
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }
    return metrics


def score_model(raw_results: dict, model_key: str, chunk_text_lookup: dict[int, str]) -> dict:
    raw_confusion = defaultdict(Counter)  # expected -> Counter(predicted)
    expected_for_metrics = []
    predicted_for_metrics = []
    parse_failures = 0
    hallucination_flags = []
    total_citing_claims = 0

    for qid, record in raw_results.items():
        expected = record["expected_tier"]
        result = record[model_key]

        if _is_parse_failure(result):
            # A parse failure (e.g. a 429) is not a genuine tier prediction -
            # counted separately below, excluded from the confusion matrix
            # and precision/recall so a rate-limit incident can't masquerade
            # as a real "Model-inference" prediction.
            parse_failures += 1
            continue

        predicted = _primary_tier(result)
        raw_confusion[expected][predicted] += 1

        # Collapsed 4-class table: merge expected Not-in-corpus into Model-inference.
        collapsed_expected = "Model-inference" if expected == "Not-in-corpus" else expected
        collapsed_predicted = predicted if predicted in SCHEMA_TIERS else "NO_CLAIMS_OR_PARSE_FAILURE"
        expected_for_metrics.append(collapsed_expected)
        predicted_for_metrics.append(collapsed_predicted)

        retrieved_chunk_ids = record["retrieved_chunk_ids"]
        for claim in result.get("claims", []):
            if claim.get("supporting_chunk_id", -1) == -1:
                continue
            total_citing_claims += 1
            flag = check_claim_grounding(claim, retrieved_chunk_ids, chunk_text_lookup)
            if flag:
                flag["question_id"] = qid
                flag["claim_text"] = claim.get("claim_text")
                hallucination_flags.append(flag)

    metrics_classes = SCHEMA_TIERS + ["NO_CLAIMS_OR_PARSE_FAILURE"]
    precision_recall = _precision_recall(expected_for_metrics, predicted_for_metrics, metrics_classes)

    accuracy_matches = sum(
        1 for e, p in zip(expected_for_metrics, predicted_for_metrics) if e == p
    )

    return {
        "raw_confusion_matrix": {k: dict(v) for k, v in raw_confusion.items()},
        "collapsed_precision_recall": precision_recall,
        "accuracy": accuracy_matches / len(expected_for_metrics) if expected_for_metrics else None,
        "n_questions": len(expected_for_metrics),
        "parse_failures": parse_failures,
        "hallucination_rate": (
            len(hallucination_flags) / total_citing_claims if total_citing_claims else None
        ),
        "hallucination_flags": hallucination_flags,
        "total_citing_claims": total_citing_claims,
        "hallucination_flag_count": len(hallucination_flags),
    }


def main() -> None:
    raw_results = json.loads(RAW_RESULTS_PATH.read_text(encoding="utf-8"))
    chunk_text_lookup = _load_chunk_text_lookup()

    scores = {
        "n_questions_scored": len(raw_results),
        "gemini": score_model(raw_results, "gemini", chunk_text_lookup),
        "groq": score_model(raw_results, "groq", chunk_text_lookup),
    }
    OUTPUT_PATH.write_text(json.dumps(scores, indent=2, default=str), encoding="utf-8")

    for model in ("gemini", "groq"):
        m = scores[model]
        print(f"\n=== {model.upper()} ===")
        print(f"n_questions: {m['n_questions']}  accuracy (collapsed 4-class): {m['accuracy']}")
        print(f"parse_failures: {m['parse_failures']}")
        print(f"hallucination_rate: {m['hallucination_rate']} "
              f"({m['hallucination_flag_count']}/{m['total_citing_claims']} citing claims)")
        for cls, stats in m["collapsed_precision_recall"].items():
            print(f"  {cls}: precision={stats['precision']} recall={stats['recall']} support={stats['support']}")

    print(f"\nFull scores written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
