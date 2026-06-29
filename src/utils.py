"""Shared utilities for the Levi's RAG pipeline."""


def is_out_of_scope(results: list[dict], threshold: float) -> bool:
    """Return True if no retrieved chunk clears the similarity threshold.

    Uses the top-1 dense similarity score as the signal. A low top-1 score
    means the corpus has no confident semantic match for the question.

    Args:
        results: List of chunk dicts from retrieve(), each containing a
            ``similarity`` key (dense cosine similarity, 0–1).
        threshold: Cosine similarity cutoff below which the question is
            considered out of scope.

    Returns:
        True when the question should be declined without calling generation.
    """
    if not results:
        return True
    return results[0]["similarity"] < threshold
