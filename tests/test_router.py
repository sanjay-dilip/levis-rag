"""Unit tests for app/router.py's classify_question() (issue #17).

Pure function tests over classify_question() only - no TestClient, no
network, no Gemini calls. Verifies the XBRL_KPI exclusion-term and
multi-year guard rules against the exact 32-question audit that motivated
the fix: 6 questions genuinely belong on XBRL_KPI (single-KPI/single-period
lookups), 26 were previously misrouted there (segment/channel, percentage-
of-total, multi-period comparison, derived/hypothetical, or qualitative
questions that happen to contain a KPI term + period token) and must now
fall through to FINANCIAL_LOOKUP.
"""

import json
from pathlib import Path

import pytest

from app.router import QuestionType, classify_question

EVAL_SET_PATH = Path("data/eval_set.json")

EXPECTED_XBRL_KPI_IDS = {
    "eval_002", "eval_005", "eval_006", "eval_042", "eval_045", "eval_057",
}
EXPECTED_NOT_XBRL_KPI_IDS = {
    # Segment/channel-specific - no whole-company XBRL tag exists.
    "eval_003", "eval_004", "eval_007", "eval_008", "eval_009", "eval_014",
    "eval_043", "eval_044",
    # Percentage-of-total.
    "eval_033", "eval_020", "eval_055", "eval_058",
    # Multi-period comparison.
    "eval_015", "eval_017", "eval_018", "eval_021", "eval_025", "eval_026",
    "eval_047", "eval_048", "eval_049", "eval_050", "eval_051", "eval_056",
    "eval_059",
    # Derived/hypothetical calculations.
    "eval_034", "eval_036", "eval_054",
    # Qualitative commentary containing a KPI term + period.
    "eval_053",
}


def _question_by_id(qid: str) -> str:
    questions = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    return next(q["question"] for q in questions if q["id"] == qid)


@pytest.mark.parametrize("qid", sorted(EXPECTED_XBRL_KPI_IDS))
def test_single_kpi_single_period_routes_to_xbrl_kpi(qid: str) -> None:
    assert classify_question(_question_by_id(qid)) is QuestionType.XBRL_KPI


@pytest.mark.parametrize("qid", sorted(EXPECTED_NOT_XBRL_KPI_IDS))
def test_segment_percentage_comparison_derived_qualitative_not_xbrl_kpi(
    qid: str,
) -> None:
    assert classify_question(_question_by_id(qid)) is not QuestionType.XBRL_KPI


def test_fy2026_guidance_question_is_out_of_scope_not_xbrl_kpi() -> None:
    """eval_037 is already intercepted by the OUT_OF_SCOPE keyword gate
    ("guidance") ahead of the XBRL_KPI check - confirm this fix didn't
    change that outcome."""
    assert classify_question(_question_by_id("eval_037")) is QuestionType.OUT_OF_SCOPE
