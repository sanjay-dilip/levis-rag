"""Shared pytest fixtures for the /query regression suite (Week 4, Task 9)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """TestClient against the real app — session-scoped since the
    Retriever/genai.Client setup (model load, BM25 index build), now built
    in app.main's lifespan startup hook rather than at import time, is
    expensive to repeat per test. Entered as a context manager so Starlette
    actually runs the lifespan startup/shutdown around the test session."""
    with TestClient(app) as test_client:
        yield test_client
