"""Shared utilities for the Levi's RAG pipeline."""

# Topics confirmed not present in the Levi's filing corpus. Intentionally
# conservative: "dockers" is included even though FY2024 10-K contains some
# Dockers figures, since a declined answer beats a partial/hallucinated one
# from a corpus that only covers the brand pre-divestiture.
OOS_KEYWORDS = [
    # Competitors
    "gap inc", "old navy", "banana republic", "vf corp", "wrangler", "lee jeans",
    "pvh", "calvin klein", "tommy hilfiger", "american eagle", "abercrombie",
    "uniqlo", "zara", "h&m",
    # Market / price data
    "stock price", "share price", "market cap", "pe ratio", "p/e ratio",
    "analyst rating", "price target", "short interest", "options",
    # Earnings call specifics not in corpus
    "earnings call", "conference call", "q&a session", "analyst question",
    "guidance",  # forward guidance is discussed on earnings calls, not filed in 10-Ks/10-Qs
    # Out-of-scope entities
    "dockers",  # divested; FY2025 10-K scope is Levi's + Beyond Yoga only
    "beyond yoga revenue",  # segment not broken out separately in corpus
]


def is_keyword_out_of_scope(question: str) -> bool:
    """Return True if the question mentions a known out-of-corpus topic.

    Simple case-insensitive substring scan against OOS_KEYWORDS, run before
    retrieval to avoid a wasted Supabase round-trip on questions that will
    never have a relevant chunk.

    Args:
        question: Natural-language question text.

    Returns:
        True when the question should be declined without retrieval.
    """
    lowered = question.lower()
    return any(keyword in lowered for keyword in OOS_KEYWORDS)


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
