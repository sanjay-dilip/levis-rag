"""Structured evidentiary tier tagging via Gemini JSON schema enforcement."""

import json
import logging
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

TIER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "The full natural language answer to the question",
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_text": {
                        "type": "string",
                        "description": (
                            "The exact sentence or phrase from the answer "
                            "that constitutes this claim"
                        ),
                    },
                    "tier": {
                        "type": "string",
                        "enum": [
                            "Verified-from-filing",
                            "Management-qualitative-statement",
                            "Third-party-benchmark",
                            "Model-inference",
                        ],
                    },
                    "supporting_chunk_id": {
                        "type": "integer",
                        "description": (
                            "The id of the retrieved chunk that supports this claim. "
                            "Use -1 if no retrieved chunk supports it directly."
                        ),
                    },
                    "fiscal_year": {
                        "type": "string",
                        "nullable": True,
                        "description": (
                            "The fiscal year the claim pertains to, e.g. FY2025. "
                            "Use null if not applicable."
                        ),
                    },
                },
                "required": ["claim_text", "tier", "supporting_chunk_id"],
            },
        },
    },
    "required": ["answer", "claims"],
}

_SYSTEM_INSTRUCTIONS = """\
You are a financial due diligence assistant analyzing SEC filings \
for Levi Strauss & Co. Answer the question using only the \
retrieved chunks provided. For every distinct claim in your \
answer, assign one of these four evidentiary tiers:

- Verified-from-filing: the exact figure or statement appears \
verbatim in a retrieved chunk from a 10-K, 10-Q, or 8-K. \
Include the chunk id in supporting_chunk_id.
- Management-qualitative-statement: the claim is a forward-looking \
or qualitative statement by Levi's management. This includes \
guidance, strategic commitments, and CEO/CFO commentary.
- Third-party-benchmark: the claim references an external source, \
index, or vendor figure mentioned in the retrieved context.
- Model-inference: the claim is a calculation or conclusion you \
derived that is not stated verbatim in any chunk.

Never invent figures. If the retrieved context does not contain \
enough information to answer, say so in the answer field and \
return a single Model-inference claim explaining the gap.\
"""

# Maps source filename patterns to fiscal year labels for context display.
_FISCAL_YEAR_LOOKUP: dict[str, str] = {
    "10-K_2026-01-28": "FY2025",
    "10-K_2025-01-29": "FY2024",
    "10-K_2024-01-25": "FY2023",
    "10-Q_2026-04-07": "FY2026",
    "10-Q_2025-10-09": "FY2025",
    "10-Q_2025-07-10": "FY2025",
    "10-Q_2025-04-07": "FY2025",
    "10-Q_2024-10-02": "FY2024",
    "10-Q_2024-06-26": "FY2024",
    "10-Q_2024-04-03": "FY2024",
}


def _fiscal_year_from_source(source: str) -> str:
    """Return the fiscal year label for a chunk's source filename."""
    for pattern, fy in _FISCAL_YEAR_LOOKUP.items():
        if pattern in source:
            return fy
    return "N/A"


def _build_prompt(question: str, context_chunks: list[dict]) -> str:
    """Assemble the structured-output prompt from the question and retrieved chunks."""
    chunk_lines = []
    for chunk in context_chunks:
        fy = _fiscal_year_from_source(chunk.get("source", ""))
        header = (
            f"Chunk id={chunk['id']} | {chunk['filing_type']} | "
            f"{fy} | {chunk['section']}"
        )
        chunk_lines.append(f"{header}\n{chunk['text']}\n---")

    context_block = "\n\n".join(chunk_lines)
    return (
        f"SYSTEM CONTEXT:\n{_SYSTEM_INSTRUCTIONS}\n\n"
        f"RETRIEVED CONTEXT:\n{context_block}\n\n"
        f"QUESTION: {question}"
    )


def tag_claims(
    question: str,
    context_chunks: list[dict],
    client: genai.Client,
) -> dict:
    """Return a structured dict with answer text and per-claim tier assignments.

    Args:
        question: The natural-language question to answer.
        context_chunks: Top-k retrieved chunks from the hybrid retriever.
        client: An initialised genai.Client instance.

    Returns:
        Dict with keys ``answer`` (str) and ``claims`` (list of dicts).
        Each claim has ``claim_text``, ``tier``, ``supporting_chunk_id``,
        and optionally ``fiscal_year``.
    """
    prompt = _build_prompt(question, context_chunks)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=TIER_SCHEMA,
            ),
        )
        return json.loads(response.text)
    except Exception as exc:
        logger.warning("tier_tagger: structured parse failed — %s", exc)
        raw = getattr(exc, "response", None)
        raw_text = response.text if "response" in dir() else str(exc)
        return {
            "answer": raw_text,
            "claims": [
                {
                    "claim_text": f"Parse failure: {exc}",
                    "tier": "Model-inference",
                    "supporting_chunk_id": -1,
                    "fiscal_year": None,
                }
            ],
        }
