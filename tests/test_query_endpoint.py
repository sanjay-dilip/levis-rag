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
