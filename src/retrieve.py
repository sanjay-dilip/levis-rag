"""Hybrid BM25 + dense retrieval with Reciprocal Rank Fusion (RRF)."""

# ROOT CAUSE: financial table chunks embed poorly in dense space (scores
# 0.11-0.20). Fix in Week 2: enrich table chunk text with section header
# and filing metadata before re-embedding, rather than tuning RRF constants.

import json
import logging
import os
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np
from dotenv import load_dotenv
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = Path("data/chunks_v2.json")
MODEL_NAME = "all-MiniLM-L6-v2"
BM25_CANDIDATES = 50
DENSE_CANDIDATES = 50
RRF_K = 60
PENALTY_RANK = 51


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


class Retriever:
    """Holds all shared state so it is initialised once and reused across queries."""

    def __init__(self, supabase: Client, chunks: list[dict], model: SentenceTransformer) -> None:
        self._supabase = supabase
        self._chunks = chunks
        self._chunks_by_id: dict[int, dict] = {c["id"]: c for c in chunks}
        self._model = model

        logger.info("Building BM25 index over %d chunks...", len(chunks))
        corpus = [_tokenize(c["text"]) for c in chunks]
        self._bm25 = BM25Okapi(corpus)

    def retrieve(self, question: str, top_k: int = 10) -> list[dict]:
        """Return the top *top_k* chunks via RRF over BM25 and dense results.

        Args:
            question: Natural-language query string.
            top_k: Number of chunks to return.

        Returns:
            List of chunk dicts enriched with bm25_rank, dense_rank, rrf_score.
        """
        # BM25 leg
        tokens = _tokenize(question)
        bm25_scores = self._bm25.get_scores(tokens)
        bm25_order = np.argsort(bm25_scores)[::-1][:BM25_CANDIDATES]
        bm25_ranks: dict[int, int] = {
            int(self._chunks[idx]["id"]): rank
            for rank, idx in enumerate(bm25_order, start=1)
        }

        # Dense leg
        query_vec = self._model.encode(question).tolist()
        response = (
            self._supabase.rpc(
                "match_chunks", {"query_embedding": query_vec, "match_count": DENSE_CANDIDATES}
            ).execute()
        )
        dense_results: list[dict] = response.data
        dense_ranks: dict[int, int] = {
            row["id"]: rank for rank, row in enumerate(dense_results, start=1)
        }

        # RRF fusion
        all_ids = set(bm25_ranks) | set(dense_ranks)
        fused: list[tuple[int, float]] = []
        for chunk_id in all_ids:
            b_rank = bm25_ranks.get(chunk_id, PENALTY_RANK)
            d_rank = dense_ranks.get(chunk_id, PENALTY_RANK)
            rrf = 1 / (RRF_K + b_rank) + 1 / (RRF_K + d_rank)
            fused.append((chunk_id, b_rank, d_rank, rrf))

        fused.sort(key=lambda x: x[3], reverse=True)

        results = []
        for chunk_id, b_rank, d_rank, rrf in fused[:top_k]:
            chunk = self._chunks_by_id.get(chunk_id)
            if chunk is None:
                # chunk came from dense leg only — build minimal dict from Supabase row
                dense_row = next(r for r in dense_results if r["id"] == chunk_id)
                chunk = dense_row
            results.append(
                {
                    "id": chunk_id,
                    "text": chunk["text"],
                    "source": chunk["source"],
                    "filing_type": chunk["filing_type"],
                    "section": chunk["section"],
                    "is_table": chunk.get("is_table", False),
                    "bm25_rank": b_rank,
                    "dense_rank": d_rank,
                    "rrf_score": rrf,
                }
            )

        return results


def build_retriever() -> Retriever:
    """Initialise and return a ready-to-use Retriever instance."""
    load_dotenv()

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    supabase = create_client(url, key)

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))

    logger.info("Loading model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    return Retriever(supabase, chunks, model)
