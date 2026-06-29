"""Hybrid BM25 + dense retrieval with Reciprocal Rank Fusion (RRF)."""

# ROOT CAUSE: financial table chunks embed poorly in dense space (scores
# 0.11-0.20). Fix in Week 2: enrich table chunk text with section header
# and filing metadata before re-embedding, rather than tuning RRF constants.

import json
import logging
import os
import re
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

# Maps filing source filename prefix → fiscal year.
# fiscal_year is not stored in chunks_v2.json (Supabase-only column), so
# the FY filter derives it from the source field returned by match_chunks.
_SOURCE_FY_MAP: dict[str, str] = {
    "10-K_2026-01-28": "FY2025",
    "10-K_2025-01-29": "FY2024",
    "10-K_2024-01-25": "FY2023",
    "10-Q_2026-04-07": "FY2026",
    "10-Q_2025-10-09": "FY2025",
    "10-Q_2025-07-10": "FY2025",
    "10-Q_2025-04-07": "FY2025",
    "10-Q_2024-10-02": "FY2024",
    "10-Q_2024-06-26": "FY2024",
    "10-Q_2024-04-03": "FY2024",
}

_FY_PATTERN = re.compile(r"FY20\d\d", re.IGNORECASE)


def _fy_from_source(source: str) -> str | None:
    """Return fiscal year for a chunk source filename, or None for 8-Ks."""
    for prefix, fy in _SOURCE_FY_MAP.items():
        if source.startswith(prefix):
            return fy
    return None


def _detect_fy(question: str) -> str | None:
    """Return the single fiscal year token if exactly one FY appears in question.

    Returns None when the question contains zero or two-or-more distinct FY
    strings (cross-year questions should not be filtered).
    """
    matches = {m.upper() for m in _FY_PATTERN.findall(question)}
    return matches.pop() if len(matches) == 1 else None


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

    def retrieve(
        self,
        question: str,
        top_k: int = 10,
        debug: bool = False,
        k: int = RRF_K,
        candidates: int = DENSE_CANDIDATES,
        fy_filter: bool = False,
    ) -> list[dict]:
        """Return the top *top_k* chunks via RRF over BM25 and dense results.

        Args:
            question: Natural-language query string.
            top_k: Number of chunks to return.
            k: RRF constant controlling rank compression.
            candidates: Number of candidates per leg before fusion.
            fy_filter: When True, restrict the dense leg to chunks whose
                fiscal year matches the single FY token in the question.
                Skipped when zero or multiple FY tokens are present.

        Returns:
            List of chunk dicts enriched with bm25_rank, dense_rank, rrf_score.
        """
        penalty = candidates + 1

        # BM25 leg
        tokens = _tokenize(question)
        bm25_scores = self._bm25.get_scores(tokens)
        bm25_order = np.argsort(bm25_scores)[::-1][:candidates]
        bm25_ranks: dict[int, int] = {
            int(self._chunks[idx]["id"]): rank
            for rank, idx in enumerate(bm25_order, start=1)
        }

        # Dense leg — over-request when FY filter is active to compensate for
        # post-filter attrition (~17% of chunks belong to any given fiscal year).
        target_fy = _detect_fy(question) if fy_filter else None
        dense_match_count = candidates * 5 if target_fy else candidates

        query_vec = self._model.encode(question).tolist()
        response = (
            self._supabase.rpc(
                "match_chunks", {"query_embedding": query_vec, "match_count": dense_match_count}
            ).limit(dense_match_count).execute()
        )
        dense_results: list[dict] = response.data

        if target_fy:
            dense_results = [
                row for row in dense_results
                if _fy_from_source(row.get("source", "")) == target_fy
            ][:candidates]

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
            b_rank = bm25_ranks.get(chunk_id, penalty)
            d_rank, d_sim = dense_ranks.get(chunk_id, (penalty, 0.0))
            rrf = 1 / (k + b_rank) + 1 / (k + d_rank)
            fused.append((chunk_id, b_rank, d_rank, rrf, d_sim))

        fused.sort(key=lambda x: (x[3], x[4]), reverse=True)

        results = []
        for chunk_id, b_rank, d_rank, rrf, d_sim in fused[:top_k]:
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
                    "similarity": d_sim,
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
