"""Heuristic question-type classification for the /query dispatch path."""

import os
import re
import sys
from enum import Enum

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from utils import is_keyword_out_of_scope

_KPI_TERMS = [
    "revenue", "gross profit", "operating income", "net income", "eps",
    "earnings per share", "inventory",
]
_PERIOD_TERMS = ["fy2025", "fy2024", "fy2026", "q1", "q2", "q3", "q4"]
_FY_YEAR_TERMS = ["fy2023", "fy2024", "fy2025", "fy2026"]

# Questions containing any of these alongside a KPI term don't map to a single
# whole-company XBRL tag: segment/channel breakdowns, percentage-of-total
# ratios, and qualitative commentary all need RAG retrieval instead.
_KPI_EXCLUSION_TERMS = [
    "dtc", "wholesale", "segment",
    "percentage", "percent", "ratio",
    "management say",
]

_TREND_TERMS = [
    "trend", "mclaren", "f1", "formula 1", "silverstone", "austin",
    "half-life", "search interest", "still active", "peaked", "fading",
]


class QuestionType(Enum):
    FINANCIAL_LOOKUP = "financial_lookup"
    TREND_QUERY = "trend_query"
    XBRL_KPI = "xbrl_kpi"
    OUT_OF_SCOPE = "out_of_scope"


def _matches_any_term(question_lower: str, terms: list[str]) -> bool:
    return any(
        re.search(r'\b' + re.escape(term) + r'\b', question_lower)
        for term in terms
    )


def _matches_kpi_term(question_lower: str) -> bool:
    return _matches_any_term(question_lower, _KPI_TERMS)


def _has_multi_period_comparison(question_lower: str) -> bool:
    """Detect whether a question references 2+ distinct fiscal years.

    A single KPI term paired with two or more fy20xx tokens (e.g. "FY2024
    and FY2025") is a comparison question, not a single-period XBRL lookup.
    """
    years = {year for year in _FY_YEAR_TERMS if re.search(r'\b' + year + r'\b', question_lower)}
    return len(years) >= 2


def classify_question(question: str) -> QuestionType:
    """Route a question to a dispatch path using ordered keyword heuristics.

    Args:
        question: Natural-language question text.

    Returns:
        The first matching QuestionType, in priority order: OUT_OF_SCOPE,
        XBRL_KPI, TREND_QUERY, then FINANCIAL_LOOKUP as the default.
    """
    if is_keyword_out_of_scope(question):
        return QuestionType.OUT_OF_SCOPE

    lowered = question.lower()

    has_kpi_term = _matches_kpi_term(lowered)
    has_period_term = any(term in lowered for term in _PERIOD_TERMS)
    if (
        has_kpi_term
        and has_period_term
        and not _matches_any_term(lowered, _KPI_EXCLUSION_TERMS)
        and not _has_multi_period_comparison(lowered)
    ):
        return QuestionType.XBRL_KPI

    if any(term in lowered for term in _TREND_TERMS):
        return QuestionType.TREND_QUERY

    return QuestionType.FINANCIAL_LOOKUP
