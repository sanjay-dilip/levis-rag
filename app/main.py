"""FastAPI application factory for the Levi's RAG Copilot backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import query as query_router

app = FastAPI(title="Levi's RAG Copilot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router.router, prefix="", tags=["query"])


@app.get("/health")
def health() -> dict:
    """Liveness check for the backend."""
    return {"status": "ok", "version": "0.1.0"}
