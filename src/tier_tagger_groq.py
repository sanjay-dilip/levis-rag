"""Structured evidentiary tier tagging via Groq / Llama 3.3 70B (issue #25).

Mirrors tier_tagger.py's tag_claims() in shape and prompt content, but
targets Groq's OpenAI-compatible chat completions endpoint instead of
Gemini. Groq does not offer schema-enforced structured output for
llama-3.3-70b-versatile (confirmed in the pre-T12 feasibility check,
CONTEXT.md) - only best-effort `json_object` mode, with the schema
serialized into the prompt as instructional text. This module therefore
adds its own post-hoc validation layer that Gemini's response_schema
gives tier_tagger.py for free.

This is a standalone research module for issue #25's model comparison.
It does not replace or alter tier_tagger.py, and is not wired into the
production /query path.
"""

import json
import logging

import requests

from tier_tagger import TIER_SCHEMA, _build_prompt, _fiscal_year_from_source  # noqa: F401

logger = logging.getLogger(__name__)

GROQ_CHAT_COMPLETIONS_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

_VALID_TIERS = {
    "Verified-from-filing",
    "Management-qualitative-statement",
    "Third-party-benchmark",
    "Model-inference",
}

_SCHEMA_INSTRUCTION = (
    "\n\nRespond with ONLY a single JSON object matching this exact "
    "schema, and nothing else - no markdown code fences, no commentary:\n"
    f"{json.dumps(TIER_SCHEMA)}"
)


def _validate_parsed(parsed: dict) -> None:
    """Raise ValueError if parsed does not conform to TIER_SCHEMA's requirements.

    Groq's json_object mode guarantees only that the response is valid
    JSON, not that it matches TIER_SCHEMA's shape - this is the
    post-hoc check that Gemini's response_schema performs mechanically.
    """
    if not isinstance(parsed, dict):
        raise ValueError("response is not a JSON object")
    if "answer" not in parsed or "claims" not in parsed:
        raise ValueError("missing required top-level key 'answer' or 'claims'")
    if not isinstance(parsed["claims"], list):
        raise ValueError("'claims' is not a list")

    for i, claim in enumerate(parsed["claims"]):
        if not isinstance(claim, dict):
            raise ValueError(f"claim[{i}] is not a JSON object")
        for key in ("claim_text", "tier", "supporting_chunk_id"):
            if key not in claim:
                raise ValueError(f"claim[{i}] missing required key '{key}'")
        if claim["tier"] not in _VALID_TIERS:
            raise ValueError(f"claim[{i}] tier '{claim['tier']}' not in enum {_VALID_TIERS}")
        if not isinstance(claim["supporting_chunk_id"], int):
            raise ValueError(f"claim[{i}] supporting_chunk_id is not an int")


def tag_claims_groq(
    question: str,
    context_chunks: list[dict],
    api_key: str,
    timeout: float = 60.0,
) -> tuple[dict, dict | None, bool]:
    """Return a structured dict with answer text and per-claim tier assignments.

    Same input/output shape as tier_tagger.tag_claims(), but calls Groq's
    llama-3.3-70b-versatile via json_object mode plus a schema serialized
    into the prompt, since Groq offers no schema enforcement for this model.

    Args:
        question: The natural-language question to answer.
        context_chunks: Top-k retrieved chunks from the hybrid retriever.
        api_key: Groq API key.
        timeout: HTTP request timeout in seconds.

    Returns:
        A tuple of (result, rate_limit_headers, success). ``result`` has
        keys ``answer`` (str) and ``claims`` (list of dicts), matching
        tag_claims()'s shape. ``rate_limit_headers`` is a dict of the
        Groq response's x-ratelimit-* headers (or None on a request-level
        failure before any response was received). ``success`` is False on
        any parse failure (HTTP error, malformed JSON, schema validation
        failure) - the caller must NOT treat rate_limit_headers as a
        reliable signal for dynamic pacing when success is False. Observed
        in practice: a 429 response can carry headers claiming a fully
        refreshed token window even though the call itself failed: trusting
        those headers computes a zero-second wait and triggers a real
        rate-limit cascade from rapid-fire retries. Always fall back to a
        fixed conservative delay after any failure instead.
    """
    prompt = _build_prompt(question, context_chunks) + _SCHEMA_INSTRUCTION

    try:
        response = requests.post(
            GROQ_CHAT_COMPLETIONS_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0,
            },
            timeout=timeout,
        )
        response.raise_for_status()
        rate_limit_headers = {
            k: v for k, v in response.headers.items() if k.lower().startswith("x-ratelimit")
        }
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        _validate_parsed(parsed)
        return parsed, rate_limit_headers, True
    except Exception as exc:
        detail = str(exc)
        try:
            detail = f"{exc} | body: {response.text[:500]}"
        except NameError:
            pass
        logger.warning("tier_tagger_groq: structured parse failed - %s", detail)
        rate_limit_headers = None
        try:
            rate_limit_headers = {
                k: v for k, v in response.headers.items() if k.lower().startswith("x-ratelimit")
            }
        except NameError:
            pass
        return {
            "answer": detail,
            "claims": [
                {
                    "claim_text": f"Parse failure: {detail}",
                    "tier": "Model-inference",
                    "supporting_chunk_id": -1,
                    "fiscal_year": None,
                }
            ],
        }, rate_limit_headers, False
