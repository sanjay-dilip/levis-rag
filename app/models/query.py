"""Pydantic request/response models for the /query endpoint."""

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    question: str
    question_type: str  # "FINANCIAL_LOOKUP" | "TREND_QUERY" | "XBRL_KPI" | "OUT_OF_SCOPE"
    answer: str
    claims: list[dict]
    chunks: list[dict]
    out_of_scope: bool
    # Structured data behind `answer`'s prose, populated only for the
    # matching question_type — get_kpi()'s result dict for XBRL_KPI,
    # analyze_drop()'s result dicts (one per drop) for TREND_QUERY. Added
    # so the frontend can render a stat card / confidence-flagged trend
    # display instead of parsing the formatted answer string (Week 4, T6).
    kpi_result: dict | None = None
    trend_results: list[dict] | None = None
