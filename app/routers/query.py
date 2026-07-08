"""POST /query route handler."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from fastapi import APIRouter
from google import genai

from retrieve import build_retriever, _fy_from_source
from tier_tagger import tag_claims
from trend_decay_tool import analyze_drop
from utils import is_out_of_scope
from xbrl_tool import get_kpi

from app.models.query import QueryRequest, QueryResponse
from app.router import QuestionType, classify_question

OUT_OF_SCOPE_THRESHOLD = 0.20
TOP_K = 10

router = APIRouter()

_retriever = build_retriever()
_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _format_drop_text(result: dict) -> str:
    """Render the status-dependent half-life summary for one drop event."""
    status = result.get("status")
    if status == "ok":
        if result.get("confidence") == "low" or result.get("warning"):
            warning = result.get("warning", "")
            return f"Half-life estimate: {result.get('half_life_weeks')} weeks — LOW CONFIDENCE. {warning}".strip()
        return (
            f"Half-life: {result.get('half_life_weeks')} weeks "
            f"({result.get('half_life_days')} days). R²={result.get('r_squared')}. "
            f"Confidence: {result.get('confidence')}. "
            f"vs report claim: {result.get('vs_report_claim')}."
        )
    if status == "insufficient_data":
        return "Insufficient signal to fit a decay curve."
    if status == "error":
        return f"Data pull failed: {result.get('error_message')}"
    return f"Status: {status}"


def _format_trend_answer(silverstone: dict, austin: dict) -> str:
    """Build the plain-English answer string for a TREND_QUERY question."""
    methodology_note = silverstone.get("methodology_note") or austin.get("methodology_note") or ""
    return (
        "Levi's McLaren search interest analysis (Google Trends):\n\n"
        f"Silverstone drop (July 3, 2024): {_format_drop_text(silverstone)}\n"
        f"Austin drop (October 17, 2024): {_format_drop_text(austin)}\n\n"
        f"Methodology: {methodology_note}\n"
        "Report claim: 6–8 week trend cycle. Interpretation requires caution — see confidence flags."
    )


def _trend_claims(silverstone: dict, austin: dict) -> list[dict]:
    """Build one tier-schema claim dict per drop event."""
    claims = []
    for result in (silverstone, austin):
        if result.get("status") == "ok":
            claims.append(
                {
                    "claim_text": (
                        f"Google Trends search interest for '{result['keyword']}' around the "
                        f"{result['label']} drop has estimated half-life of "
                        f"{result.get('half_life_weeks')} weeks (R²={result.get('r_squared')})"
                    ),
                    "tier": "Third-party-benchmark",
                    "supporting_chunk_id": -1,
                    "fiscal_year": None,
                }
            )
        else:
            claims.append(
                {
                    "claim_text": result.get("status"),
                    "tier": "Model-inference",
                    "supporting_chunk_id": -1,
                    "fiscal_year": None,
                }
            )
    return claims


def _format_kpi_answer(result: dict) -> str:
    """Render the status-dependent answer string for an XBRL_KPI question."""
    status = result.get("status")
    if status == "ok":
        return (
            f"Levi's {result['kpi']} for {result['period']}: "
            f"{result['value']:,} {result['unit']} "
            f"(Source: {result['form']} filed {result['filed']}, EDGAR XBRL)"
        )
    if status == "no_kpi_match":
        return (
            "Could not identify a specific KPI in that question. Try asking "
            "about revenue, gross profit, operating income, net income, EPS, or inventory."
        )
    if status == "no_period_match":
        return "Please specify a fiscal period (e.g. FY2025, Q1 FY2025)."
    if status == "not_found":
        return (
            f"No XBRL fact found for {result.get('kpi')} in {result.get('period')}. "
            "This period may not be tagged in EDGAR or may predate XBRL filing requirements."
        )
    return f"Status: {status}"


def _kpi_claim(result: dict) -> dict:
    """Build a single tier-schema claim dict for an XBRL_KPI question."""
    return {
        "claim_text": _format_kpi_answer(result),
        "tier": result.get("tier", "Model-inference"),
        "supporting_chunk_id": -1,
        "fiscal_year": None,
    }


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
            question_type=question_type.name,
            answer="This question is outside the Levi's filing corpus.",
            claims=[],
            chunks=[],
            out_of_scope=True,
        )

    if question_type == QuestionType.TREND_QUERY:
        silverstone = analyze_drop("silverstone_2024")
        austin = analyze_drop("austin_2024")

        return QueryResponse(
            question=request.question,
            question_type=question_type.name,
            answer=_format_trend_answer(silverstone, austin),
            claims=_trend_claims(silverstone, austin),
            chunks=[],
            out_of_scope=False,
            trend_results=[silverstone, austin],
        )

    if question_type == QuestionType.XBRL_KPI:
        kpi_result = get_kpi(request.question)
        answer = _format_kpi_answer(kpi_result)
        return QueryResponse(
            question=request.question,
            question_type=question_type.name,
            answer=answer,
            claims=[_kpi_claim(kpi_result)],
            chunks=[],
            out_of_scope=False,
            kpi_result=kpi_result,
        )

    # FINANCIAL_LOOKUP — existing RAG pipeline
    hits = _retriever.retrieve(request.question, top_k=TOP_K)
    stripped_chunks = [_strip_chunk(chunk) for chunk in hits]

    if is_out_of_scope(hits, OUT_OF_SCOPE_THRESHOLD):
        return QueryResponse(
            question=request.question,
            question_type=question_type.name,
            answer="This question is outside the Levi's filing corpus.",
            claims=[],
            chunks=stripped_chunks,
            out_of_scope=True,
        )

    result = tag_claims(request.question, hits, _client)

    return QueryResponse(
        question=request.question,
        question_type=question_type.name,
        answer=result.get("answer", ""),
        claims=result.get("claims", []),
        chunks=stripped_chunks,
        out_of_scope=False,
    )
