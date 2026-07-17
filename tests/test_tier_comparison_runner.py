"""Unit tests for src/tier_comparison_runner.py's resumability and
quota-waste fix (issue #31).

Pure/mocked tests only - no network, no live Gemini/Groq calls, no
Supabase, no model loading. Verifies two things directly rather than by
assumption:

1. The skip-already-done check (_compute_remaining/_done_ids) actually
   excludes questions that already have a genuine result on both sides,
   and actually retries questions with a parse failure on either side.
2. On a Gemini RESOURCE_EXHAUSTED (daily quota) result, _process_question
   stops immediately - exactly one Gemini call, zero Groq calls, nothing
   returned to save - rather than retrying or wasting a Groq call on a
   question that can't be completed today anyway.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

import tier_comparison_runner as runner


def _good_result(tier="Verified-from-filing", chunk_id=604):
    return {
        "answer": "61.7%",
        "claims": [
            {
                "claim_text": "Levi's FY2025 gross margin was 61.7%.",
                "tier": tier,
                "supporting_chunk_id": chunk_id,
                "fiscal_year": "FY2025",
            }
        ],
    }


def _exhausted_result():
    return {
        "answer": "429 RESOURCE_EXHAUSTED. ...",
        "claims": [
            {
                "claim_text": (
                    "Parse failure: 429 RESOURCE_EXHAUSTED. {'error': "
                    "{'code': 429, 'status': 'RESOURCE_EXHAUSTED', "
                    "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}}"
                ),
                "tier": "Model-inference",
                "supporting_chunk_id": -1,
                "fiscal_year": None,
            }
        ],
    }


def _other_parse_failure():
    return {
        "answer": "boom",
        "claims": [
            {
                "claim_text": "Parse failure: json.decoder.JSONDecodeError",
                "tier": "Model-inference",
                "supporting_chunk_id": -1,
                "fiscal_year": None,
            }
        ],
    }


class TestIsResourceExhausted:
    def test_true_on_resource_exhausted_claim(self):
        assert runner._is_resource_exhausted(_exhausted_result()) is True

    def test_false_on_genuine_result(self):
        assert runner._is_resource_exhausted(_good_result()) is False

    def test_false_on_other_parse_failure(self):
        assert runner._is_resource_exhausted(_other_parse_failure()) is False


class TestDoneIdsAndRemaining:
    EVAL_SET = [
        {"id": "eval_001", "question": "q1", "expected_tier": "t", "question_type": "x"},
        {"id": "eval_002", "question": "q2", "expected_tier": "t", "question_type": "x"},
        {"id": "eval_003", "question": "q3", "expected_tier": "t", "question_type": "x"},
    ]

    def test_done_ids_requires_both_sides_genuine(self):
        existing = {
            "eval_001": {"gemini": _good_result(), "groq": _good_result()},
            "eval_002": {"gemini": _good_result(), "groq": _other_parse_failure()},
        }
        assert runner._done_ids(existing) == {"eval_001"}

    def test_compute_remaining_skips_done_and_retries_failed(self):
        existing = {
            "eval_001": {"gemini": _good_result(), "groq": _good_result()},
            "eval_002": {"gemini": _good_result(), "groq": _other_parse_failure()},
        }
        remaining = runner._compute_remaining(self.EVAL_SET, existing, max_total=None)
        remaining_ids = [q["id"] for q in remaining]
        # eval_001 done on both sides -> skipped. eval_002 has a groq
        # failure -> retried. eval_003 never attempted -> included.
        assert remaining_ids == ["eval_002", "eval_003"]

    def test_compute_remaining_respects_max_total(self):
        existing = {
            "eval_001": {"gemini": _good_result(), "groq": _good_result()},
        }
        remaining = runner._compute_remaining(self.EVAL_SET, existing, max_total=2)
        # 1 already done, max_total=2 -> only 1 more needed.
        assert [q["id"] for q in remaining] == ["eval_002"]

    def test_compute_remaining_never_recomputes_a_call_for_a_done_question(self):
        """The actual resumability guarantee: a fully-done question never
        reappears in `remaining`, regardless of how many times this is
        called - i.e. re-running the script does not silently re-call
        Gemini/Groq for it."""
        existing = {q["id"]: {"gemini": _good_result(), "groq": _good_result()} for q in self.EVAL_SET}
        remaining = runner._compute_remaining(self.EVAL_SET, existing, max_total=None)
        assert remaining == []


class _StubRetriever:
    def retrieve(self, question, top_k):
        return [{"id": 604}, {"id": 602}]


class TestProcessQuestionStopsOnExhaustion:
    QUESTION = {
        "id": "eval_099",
        "question": "What was Levi's FY2025 gross margin?",
        "expected_tier": "Verified-from-filing",
        "question_type": "numeric_lookup",
    }

    def test_stops_immediately_no_retry_no_groq_call(self, monkeypatch):
        gemini_calls = []
        groq_calls = []

        def fake_tag_claims(question, hits, client):
            gemini_calls.append(question)
            return _exhausted_result()

        def fake_tag_claims_groq(question, hits, api_key):
            groq_calls.append(question)
            return _good_result(), {}, True

        monkeypatch.setattr(runner, "tag_claims", fake_tag_claims)
        monkeypatch.setattr(runner, "tag_claims_groq", fake_tag_claims_groq)
        monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

        record, gemini_exhausted = runner._process_question(
            self.QUESTION, gemini_client=object(), groq_api_key="fake", retriever=_StubRetriever()
        )

        assert gemini_exhausted is True
        assert record is None
        # Exactly one Gemini call attempted - confirms no retry loop.
        assert len(gemini_calls) == 1
        # Groq must never be called once Gemini is confirmed exhausted.
        assert len(groq_calls) == 0

    def test_normal_success_calls_both_and_returns_record(self, monkeypatch):
        monkeypatch.setattr(runner, "tag_claims", lambda q, h, c: _good_result())
        monkeypatch.setattr(
            runner, "tag_claims_groq", lambda q, h, k: (_good_result(), {"x": "y"}, True)
        )
        monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

        record, gemini_exhausted = runner._process_question(
            self.QUESTION, gemini_client=object(), groq_api_key="fake", retriever=_StubRetriever()
        )

        assert gemini_exhausted is False
        assert record is not None
        assert record["question"] == self.QUESTION["question"]
        assert record["retrieved_chunk_ids"] == [604, 602]
        assert record["gemini"]["claims"][0]["tier"] == "Verified-from-filing"
        assert record["groq_rate_limit_headers"] == {"x": "y"}

    def test_non_quota_gemini_failure_does_not_stop_and_still_calls_groq(self, monkeypatch):
        """A non-quota failure (e.g. malformed JSON) is a different problem
        from daily-quota exhaustion - it should NOT hard-stop the run, and
        Groq's genuine result for the question should still be captured."""
        groq_calls = []

        def fake_tag_claims_groq(question, hits, api_key):
            groq_calls.append(question)
            return _good_result(), {}, True

        monkeypatch.setattr(runner, "tag_claims", lambda q, h, c: _other_parse_failure())
        monkeypatch.setattr(runner, "tag_claims_groq", fake_tag_claims_groq)
        monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)

        record, gemini_exhausted = runner._process_question(
            self.QUESTION, gemini_client=object(), groq_api_key="fake", retriever=_StubRetriever()
        )

        assert gemini_exhausted is False
        assert record is not None
        assert len(groq_calls) == 1
