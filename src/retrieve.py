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
BM25_CANDIDATES = 100
DENSE_CANDIDATES = 100
RRF_K = 60
PENALTY_RANK = 101


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

    def retrieve(self, question: str, top_k: int = 10, debug: bool = False) -> list[dict]:
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
            ).limit(DENSE_CANDIDATES).execute()
        )
        dense_results: list[dict] = response.data
        # Store (rank, similarity) so similarity can break RRF ties below.
        dense_ranks: dict[int, tuple[int, float]] = {
            row["id"]: (rank, row["similarity"])
            for rank, row in enumerate(dense_results, start=1)
        }

        if debug:
            print(f"\n--- Dense top-20 (pre-RRF) for: {question!r} ---\n")
            for rank, row in enumerate(dense_results[:20], start=1):
                chunk_meta = self._chunks_by_id.get(row["id"], {})
                print(
                    f"[{rank:2d}] id={row['id']:5d}  sim={row['similarity']:.4f}"
                    f"  is_table={str(row.get('is_table', chunk_meta.get('is_table', '?'))):5s}"
                    f"  {row.get('filing_type', chunk_meta.get('filing_type', '?')):5s}"
                    f"  src={row.get('source', chunk_meta.get('source', '?'))[:35]:35s}"
                    f"  sec={row.get('section', chunk_meta.get('section', '?'))[:30]:30s}"
                    f"  txt={row['text'][:80]!r}"
                )
            print()

        # RRF fusion
        # When a chunk appears in only one leg, its single-leg score is
        # 1/(k+rank) + 1/(k+penalty). For equal rank N, BM25-only and
        # dense-only chunks produce identical RRF scores.  Break those ties
        # by dense similarity so well-matched dense chunks surface correctly.
        all_ids = set(bm25_ranks) | set(dense_ranks)
        fused: list[tuple[int, float]] = []
        for chunk_id in all_ids:
            b_rank = bm25_ranks.get(chunk_id, PENALTY_RANK)
            d_rank, d_sim = dense_ranks.get(chunk_id, (PENALTY_RANK, 0.0))
            rrf = 1 / (RRF_K + b_rank) + 1 / (RRF_K + d_rank)
            fused.append((chunk_id, b_rank, d_rank, rrf, d_sim))

        fused.sort(key=lambda x: (x[3], x[4]), reverse=True)

        results = []
        for chunk_id, b_rank, d_rank, rrf, _d_sim in fused[:top_k]:
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
    # Service key required: anon role lacks EXECUTE on match_chunks RPC.
    key = os.environ["SUPABASE_SERVICE_KEY"]
    supabase = create_client(url, key)

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))

    logger.info("Loading model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    return Retriever(supabase, chunks, model)
