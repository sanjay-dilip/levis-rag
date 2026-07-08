"""Regression tests for the POST /query endpoint (Week 4, Task 9)."""

from fastapi.testclient import TestClient


def test_placeholder() -> None:
    """Proves pytest discovery and the tests/ import path work before real tests are added."""
    assert True


def test_health(client: TestClient) -> None:
    """Confirms the TestClient fixture can reach the app in-process."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "0.1.0"}


def _query(client: TestClient, question: str) -> dict:
    response = client.post("/query", json={"question": question})
    assert response.status_code == 200
    return response.json()


def test_financial_lookup_gross_margin(client: TestClient) -> None:
    """FINANCIAL_LOOKUP success path — RAG pipeline, mirrors T1/T3's gross margin check.

    Ground truth (61.7%) confirmed repeatedly since Week 2, Session 2 — chunk 604.
    """
    body = _query(client, "What was Levi's FY2025 gross margin?")
    assert body["question_type"] == "FINANCIAL_LOOKUP"
    assert body["out_of_scope"] is False
    assert "61.7%" in body["answer"]


def test_xbrl_kpi_gross_profit(client: TestClient) -> None:
    """XBRL_KPI path — EDGAR companyfacts lookup, mirrors T7/T9's gross profit check.

    Asserts two previously-broken things: the Week 4 T1 Fix 1 bug (get_kpi()'s "period"
    field read "FY FY2025" instead of "FY2025" for annual lookups), and the Task 7 ground
    truth value itself ($3,877,800,000 — matches 61.7% x $6,282.0M within rounding).
    """
    body = _query(client, "What was Levi's gross profit in FY2025?")
    assert body["question_type"] == "XBRL_KPI"
    assert body["out_of_scope"] is False
    kpi_result = body["kpi_result"]
    assert kpi_result["status"] == "ok"
    assert kpi_result["period"] == "FY2025"  # not "FY FY2025" — T1 Fix 1 regression
    assert kpi_result["value"] == 3877800000  # Task 7 ground truth


def test_xbrl_kpi_net_income_profitloss_regression(client: TestClient) -> None:
    """XBRL_KPI path — Task 8's ProfitLoss/NetIncomeLoss tag-priority bug.

    Levi's FY2025 10-K tags full-year net income under the GAAP concept "ProfitLoss", not
    "NetIncomeLoss" (which has zero fp="FY" entries for fy 2025/2026 in the cached facts).
    Before the Task 8 fix, this returned status="not_found" instead of $578,100,000.
    """
    body = _query(client, "What was Levi's net income in FY2025?")
    assert body["question_type"] == "XBRL_KPI"
    kpi_result = body["kpi_result"]
    assert kpi_result["status"] == "ok"
    assert kpi_result["gaap_tag"] == "ProfitLoss"
    assert kpi_result["value"] == 578100000


def test_trend_query_mclaren(client: TestClient) -> None:
    """TREND_QUERY path — Google Trends decay tool, mirrors T6's McLaren check."""
    body = _query(client, "Is the McLaren trend still active?")
    assert body["question_type"] == "TREND_QUERY"
    assert body["out_of_scope"] is False


def test_out_of_scope_keyword_gate_vf_corp(client: TestClient) -> None:
    """OUT_OF_SCOPE via the keyword gate — competitor question, never reaches retrieval."""
    body = _query(client, "What is VF Corporation's gross margin?")
    assert body["question_type"] == "OUT_OF_SCOPE"
    assert body["out_of_scope"] is True
    assert body["claims"] == []
    assert body["chunks"] == []


def test_financial_lookup_oos_similarity_branch_market_share(client: TestClient) -> None:
    """FINANCIAL_LOOKUP via the OOS-similarity branch — eval_041, item #12's documented gap.

    The keyword gate does NOT catch "market share" (deliberately, per item #12), and the
    similarity-threshold gate doesn't fire either (top chunk similarity ~0.60, well above the
    0.20 threshold) — so this currently resolves as out_of_scope: False, with Gemini declining
    inside its own answer text instead. Asserting the actual current behavior on purpose: if
    this gap is ever closed, it should be a deliberate change, not something that silently
    flips this assertion without anyone noticing.
    """
    body = _query(client, "What is Levi's market share in the global denim market?")
    assert body["question_type"] == "FINANCIAL_LOOKUP"
    assert body["out_of_scope"] is False
