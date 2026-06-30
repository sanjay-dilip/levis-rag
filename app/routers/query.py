"""POST /query route handler."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from fastapi import APIRouter
from google import genai

from retrieve import build_retriever, _fy_from_source
from tier_tagger import tag_claims
from utils import is_out_of_scope

from app.models.query import QueryRequest, QueryResponse
from app.router import QuestionType, classify_question

OUT_OF_SCOPE_THRESHOLD = 0.20
TOP_K = 10

router = APIRouter()

_retriever = build_retriever()
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _strip_chunk(chunk: dict) -> dict:
    """Drop the chunk text and keep only the fields the response needs."""
    return {
        "id": chunk["id"],
        "source": chunk["source"],
        "filing_type": chunk["filing_type"],
        "section": chunk["section"],
        "fiscal_year": _fy_from_source(chunk.get("source", "")),
        "rrf_score": chunk["rrf_score"],
        "similarity": chunk["similarity"],
    }


@router.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """Run hybrid retrieval, OOS gating, and tiered generation for a question."""
    question_type = classify_question(request.question)

    if question_type == QuestionType.OUT_OF_SCOPE:
        return QueryResponse(
            question=request.question,
            answer="This question is outside the Levi's filing corpus.",
            claims=[],
            chunks=[],
            out_of_scope=True,
        )

    if question_type == QuestionType.TREND_QUERY:
        return QueryResponse(
            question=request.question,
            answer="Trend analysis tool not yet implemented.",
            claims=[],
            chunks=[],
            out_of_scope=False,
        )

    if question_type == QuestionType.XBRL_KPI:
        return QueryResponse(
            question=request.question,
            answer="XBRL KPI extraction not yet implemented.",
            claims=[],
            chunks=[],
            out_of_scope=False,
        )

    # FINANCIAL_LOOKUP — existing RAG pipeline
    hits = _retriever.retrieve(request.question, top_k=TOP_K)
    stripped_chunks = [_strip_chunk(chunk) for chunk in hits]

    if is_out_of_scope(hits, OUT_OF_SCOPE_THRESHOLD):
        return QueryResponse(
            question=request.question,
            answer="This question is outside the Levi's filing corpus.",
            claims=[],
            chunks=stripped_chunks,
            out_of_scope=True,
        )

    result = tag_claims(request.question, hits, _client)

    return QueryResponse(
        question=request.question,
        answer=result.get("answer", ""),
        claims=result.get("claims", []),
        chunks=stripped_chunks,
        out_of_scope=False,
    )
