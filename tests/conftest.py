"""Shared pytest fixtures for the /query regression suite (Week 4, Task 9)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """TestClient against the real app — session-scoped since app.main's
    module-level Retriever/genai.Client setup (model load, BM25 index build)
    is expensive to repeat per test."""
    return TestClient(app)
