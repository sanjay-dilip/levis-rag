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
