"""Retrieval evaluation runner for the Levi's RAG eval set.

Loads data/eval_set.json, runs each question through the same dispatch order
as app/router.py (keyword OOS gate, then the hybrid retriever's own
similarity-threshold OOS gate), scores retrieval as HIT / PARTIAL / MISS,
prints a summary, and saves per-question results to data/eval_results.json.

Tier-tagging evaluation is out of scope for this script — retrieval only.
"""

import argparse
import json
import logging
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

from retrieve import build_retriever
from utils import is_keyword_out_of_scope, is_out_of_scope

OUT_OF_SCOPE_THRESHOLD = 0.20

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

EVAL_SET_PATH = Path("data/eval_set.json")
RESULTS_PATH = Path("data/eval_results.json")
TOP_K = 10

HIT = "HIT"
PARTIAL = "PARTIAL"
MISS = "MISS"


def score_retrieval(
    returned_ids: list[int],
    ground_truth_ids: list[int],
    acceptable_ids: list[int],
) -> str:
    """Return HIT, PARTIAL, or MISS given the retrieved and expected chunk ids.

    Args:
        returned_ids: Chunk ids returned by the retriever (top-k).
        ground_truth_ids: Primary chunk ids that must appear for a HIT.
        acceptable_ids: Secondary chunk ids that count as PARTIAL credit.

    Returns:
        ``HIT`` if any ground-truth id is in returned_ids.
        ``PARTIAL`` if no ground-truth id but an acceptable id is present.
        ``MISS`` otherwise.
    """
    returned_set = set(returned_ids)
    if any(cid in returned_set for cid in ground_truth_ids):
        return HIT
    if any(cid in returned_set for cid in acceptable_ids):
        return PARTIAL
    return MISS


def run_eval(
    eval_entries: list[dict],
    retriever,
    k: int = 60,
    candidates: int = 100,
    fy_filter: bool = False,
) -> list[dict]:
    """Run retrieval for every eval entry and return annotated results.

    Args:
        eval_entries: Loaded eval_set.json entries.
        retriever: An initialised Retriever instance.
        k: RRF constant passed to retriever.
        candidates: Candidates per leg passed to retriever.
        fy_filter: Whether to restrict the dense leg by detected fiscal year.

    Returns:
        List of eval entry dicts enriched with ``retrieval_result`` and
        ``returned_chunk_ids``.
    """
    results = []
    for entry in eval_entries:
        question = entry["question"]
        result = entry.copy()

        if is_keyword_out_of_scope(question):
            # Mirrors app/router.py's dispatch order: the keyword gate is
            # checked before retrieval runs at all, so no chunks are fetched.
            result["keyword_oos_triggered"] = True
            result["returned_chunk_ids"] = []
            verdict = MISS
            if entry.get("question_type") != "out_of_scope":
                result["keyword_oos_false_positive"] = True
        else:
            hits = retriever.retrieve(question, top_k=TOP_K, k=k, candidates=candidates, fy_filter=fy_filter)
            returned_ids = [h["id"] for h in hits]
            result["returned_chunk_ids"] = returned_ids

            if is_out_of_scope(hits, OUT_OF_SCOPE_THRESHOLD):
                # Out-of-scope gate fired: correct for out_of_scope questions, a
                # false positive for any in-scope type.
                verdict = MISS
                if entry.get("question_type") != "out_of_scope":
                    result["oos_false_positive"] = True
            else:
                verdict = score_retrieval(
                    returned_ids,
                    entry.get("ground_truth_chunk_ids", []),
                    entry.get("acceptable_chunk_ids", []),
                )

        result["retrieval_result"] = verdict
        results.append(result)
    return results


def print_summary(results: list[dict]) -> None:
    """Print the retrieval evaluation summary to stdout."""
    total = len(results)
    counts = {HIT: 0, PARTIAL: 0, MISS: 0}
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: {HIT: 0, PARTIAL: 0, MISS: 0})
    misses = []

    false_positives = []
    keyword_triggered = []
    keyword_false_positives = []
    for r in results:
        verdict = r["retrieval_result"]
        qtype = r.get("question_type", "unknown")
        counts[verdict] += 1
        by_type[qtype][verdict] += 1
        if verdict == MISS:
            misses.append(r)
        if r.get("oos_false_positive"):
            false_positives.append(r)
        if r.get("keyword_oos_triggered"):
            keyword_triggered.append(r)
        if r.get("keyword_oos_false_positive"):
            keyword_false_positives.append(r)

    def pct(n: int) -> str:
        return f"{n / total * 100:.1f}%" if total else "0.0%"

    print("\nRETRIEVAL EVALUATION SUMMARY")
    print("-" * 33)
    print(f"Total questions:     {total}")
    print(f"Hits (recall@10):    {counts[HIT]}  ({pct(counts[HIT])})")
    print(f"Partials:            {counts[PARTIAL]}  ({pct(counts[PARTIAL])})")
    print(f"Misses:              {counts[MISS]}  ({pct(counts[MISS])})")

    print("\nBY QUESTION TYPE:")
    for qtype in sorted(by_type):
        t = by_type[qtype]
        print(
            f"  {qtype:<22} -- Hit: {t[HIT]} | Partial: {t[PARTIAL]} | Miss: {t[MISS]}"
        )

    if false_positives:
        print("\nOOS FALSE POSITIVES (in-scope questions intercepted by threshold):")
        for r in false_positives:
            top_sim = r["returned_chunk_ids"] and "see eval_results.json"
            print(f"  [{r['id']}] {r['question']}")
    else:
        print("\nNo OOS false positives.")

    out_of_scope_total = sum(
        1 for r in results if r.get("question_type") == "out_of_scope"
    )
    keyword_correct = [r for r in keyword_triggered if r not in keyword_false_positives]
    print("\nKEYWORD OOS GATE (is_keyword_out_of_scope, checked before retrieval):")
    print(
        f"  Correctly caught {len(keyword_correct)}/{out_of_scope_total} out_of_scope questions"
    )
    if keyword_triggered:
        for r in keyword_triggered:
            tag = "FALSE POSITIVE" if r in keyword_false_positives else "correct rejection"
            print(f"  [{r['id']}] ({tag}) {r['question']}")
    if keyword_false_positives:
        print(f"  WARNING: {len(keyword_false_positives)} in-scope question(s) falsely intercepted by the keyword gate.")
    else:
        print("  No keyword-gate false positives.")

    if misses:
        print("\nMISSES:")
        for r in misses:
            print(f"  [{r['id']}] {r['question']}")
            print(f"         returned chunks: {r['returned_chunk_ids']}")
    else:
        print("\nNo misses.")


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Retrieval evaluation runner")
    parser.add_argument("--k", type=int, default=60, help="RRF k constant")
    parser.add_argument("--candidates", type=int, default=100, help="Candidates per leg")
    parser.add_argument("--fy-filter", action="store_true", default=False, help="Filter dense leg by fiscal year")
    args = parser.parse_args()

    print(f"CONFIG: k={args.k} | candidates={args.candidates} | fy_filter={args.fy_filter}")

    eval_entries = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    if not eval_entries:
        logger.info("eval_set.json is empty — nothing to evaluate.")
        return

    logger.info("Building retriever...")
    retriever = build_retriever()

    logger.info("Running %d eval questions...", len(eval_entries))
    results = run_eval(eval_entries, retriever, k=args.k, candidates=args.candidates, fy_filter=args.fy_filter)

    print_summary(results)

    RESULTS_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("\nResults saved to %s", RESULTS_PATH)


if __name__ == "__main__":
    main()
