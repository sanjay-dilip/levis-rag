"""Structural smoke test over data/eval_set.json (Week 4, Task 9.5).

Distinct purpose from src/eval_runner.py: eval_runner.py measures retrieval
quality (recall@10 against ground-truth chunk ids) and is run manually/
periodically. This test only checks that a sample of the 60 hand-labeled
questions doesn't 500 and returns a well-formed QueryResponse shape — a
fast, cheap check meant to run on every commit. Runs a deterministic
stratified sample (2 questions per question_type category, 10 total) rather
than all 60, since each question is a real Gemini/EDGAR/pytrends call —
running all 60 on every commit would be slow and not free.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

EVAL_SET_PATH = Path("data/eval_set.json")
SAMPLE_SIZE_PER_CATEGORY = 2


def _load_stratified_sample() -> list[dict]:
    """First N questions per question_type category, sorted by id for determinism."""
    questions = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
    by_category: dict[str, list[dict]] = {}
    for question in sorted(questions, key=lambda q: q["id"]):
        by_category.setdefault(question["question_type"], []).append(question)

    sample = []
    for category_questions in by_category.values():
        sample.extend(category_questions[:SAMPLE_SIZE_PER_CATEGORY])
    return sample


EVAL_SAMPLE = _load_stratified_sample()


@pytest.mark.parametrize(
    "eval_question",
    EVAL_SAMPLE,
    ids=[q["id"] for q in EVAL_SAMPLE],
)
def test_eval_question_returns_well_formed_response(
    client: TestClient, eval_question: dict
) -> None:
    """No 500, and the response has the shape QueryResponse promises — not a correctness check."""
    response = client.post("/query", json={"question": eval_question["question"]})
    assert response.status_code == 200

    body = response.json()
    assert isinstance(body["question"], str)
    assert body["question_type"] in (
        "FINANCIAL_LOOKUP",
        "TREND_QUERY",
        "XBRL_KPI",
        "OUT_OF_SCOPE",
    )
    assert isinstance(body["answer"], str)
    assert isinstance(body["claims"], list)
    assert isinstance(body["chunks"], list)
    assert isinstance(body["out_of_scope"], bool)
    for claim in body["claims"]:
        assert claim["tier"] in (
            "Verified-from-filing",
            "Management-qualitative-statement",
            "Third-party-benchmark",
            "Model-inference",
        )
        assert isinstance(claim["supporting_chunk_id"], int)
