"""FastAPI application factory for the Levi's RAG Copilot backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import query as query_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the Retriever/genai.Client after the port is bound, not before.

    Keeps the existing "build once, not per-request" design -- just moves
    the expensive model load out of import time so uvicorn can bind $PORT
    immediately (required for Render's port-scan check to succeed).
    """
    query_router.init_dependencies()
    yield


app = FastAPI(title="Levi's RAG Copilot", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://levis-rag.vercel.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(query_router.router, prefix="", tags=["query"])


@app.get("/health")
def health() -> dict:
    """Liveness check for the backend."""
    return {"status": "ok", "version": "0.1.0"}
