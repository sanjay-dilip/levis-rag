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
import onnxruntime as ort
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download
from rank_bm25 import BM25Okapi
from tokenizers import Tokenizer
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = Path("data/chunks_v2.json")
MODEL_NAME = "all-MiniLM-L6-v2"
MODEL_REPO = "sentence-transformers/all-MiniLM-L6-v2"
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

# Maps 10-Q source filename prefix → quarter label, derived from the same
# period-of-report dates used in fix_fiscal_year_metadata.py. 10-Ks and 8-Ks
# have no quarter (annual / event-driven) and are absent from this map.
_SOURCE_QUARTER_MAP: dict[str, str] = {
    "10-Q_2026-04-07": "Q1",  # period 2026-03-01
    "10-Q_2025-10-09": "Q3",  # period 2025-08-31
    "10-Q_2025-07-10": "Q2",  # period 2025-06-01
    "10-Q_2025-04-07": "Q1",  # period 2025-03-02
    "10-Q_2024-10-02": "Q3",  # period 2024-08-25
    "10-Q_2024-06-26": "Q2",  # period 2024-05-26
    "10-Q_2024-04-03": "Q1",  # period 2024-02-25
}

_FY_PATTERN = re.compile(r"FY(20\d\d)", re.IGNORECASE)
_QUARTER_PATTERN = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)


def _fy_from_source(source: str) -> str | None:
    """Return fiscal year for a chunk source filename, or None for 8-Ks."""
    for prefix, fy in _SOURCE_FY_MAP.items():
        if source.startswith(prefix):
            return fy
    return None


def _quarter_from_source(source: str) -> str | None:
    """Return quarter label ("Q1".."Q4") for a 10-Q source, or None for 10-Ks/8-Ks."""
    for prefix, quarter in _SOURCE_QUARTER_MAP.items():
        if source.startswith(prefix):
            return quarter
    return None


def _detect_period(question: str) -> tuple[str | None, str | None]:
    """Return (fiscal_year, quarter) tokens detected in the question.

    fiscal_year is the FY token to filter on, or None if the question names
    no fiscal year (cross-year and quarter-specific questions should not be
    filtered by the caller in that case). When multiple distinct FY tokens
    appear (e.g. "between FY2024 and FY2025"), the latest year is used --
    later filings carry the prior year(s) as restated comparatives in the
    same chunk, so filtering to the latest year's filing still surfaces the
    answer.

    quarter is a single "Q1".."Q4" token if exactly one distinct quarter
    token appears, else None (no quarter-level filtering).
    """
    years = {m for m in _FY_PATTERN.findall(question)}
    if not years:
        return None, None
    fy = f"FY{max(years)}"

    quarters = {m.upper() for m in _QUARTER_PATTERN.findall(question)}
    quarter = f"Q{quarters.pop()}" if len(quarters) == 1 else None

    # Levi's Q4 is never filed as its own 10-Q -- the fourth quarter is only
    # ever reported inline in the annual 10-K, which chunk-level metadata
    # tags as annual (quarter=None), not "Q4". Treating "Q4" as a quarter
    # filter would match zero chunks and starve both legs. Fall back to
    # FY-only filtering, which correctly matches the 10-K.
    if quarter == "Q4":
        quarter = None

    return fy, quarter


def _tokenize(text: str) -> list[str]:
    return text.lower().split()


def _encode(text: str, tokenizer: Tokenizer, session: ort.InferenceSession) -> list[float]:
    """Encode text to a 384-dim embedding matching SentenceTransformer's own
    output for this model: mean-pool token embeddings (weighted by the
    attention mask), then L2-normalize -- the exact pipeline this model's
    own modules.json specifies (Transformer -> Pooling(mean) -> Normalize).
    Verified against the local sentence-transformers output (cosine 1.0,
    max elementwise diff ~1e-7) before relying on this in production.
    """
    encoded = tokenizer.encode(text)
    input_ids = np.array([encoded.ids], dtype=np.int64)
    attention_mask = np.array([encoded.attention_mask], dtype=np.int64)

    ort_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
    input_names = {i.name for i in session.get_inputs()}
    if "token_type_ids" in input_names:
        ort_inputs["token_type_ids"] = np.zeros_like(input_ids)

    token_embeddings = session.run(None, ort_inputs)[0]  # [1, seq_len, 384]

    mask = attention_mask[..., None].astype(np.float32)
    summed = (token_embeddings * mask).sum(axis=1)
    counts = np.clip(mask.sum(axis=1), a_min=1e-9, a_max=None)
    mean_pooled = summed / counts

    norm = np.linalg.norm(mean_pooled, axis=1, keepdims=True)
    normalized = mean_pooled / norm

    return normalized[0].tolist()


class Retriever:
    """Holds all shared state so it is initialised once and reused across queries."""

    def __init__(
        self,
        supabase: Client,
        chunks: list[dict],
        tokenizer: Tokenizer,
        onnx_session: ort.InferenceSession,
    ) -> None:
        self._supabase = supabase
        self._chunks = chunks
        self._chunks_by_id: dict[int, dict] = {c["id"]: c for c in chunks}
        self._tokenizer = tokenizer
        self._onnx_session = onnx_session

        # (fiscal_year, quarter) per chunk, aligned with `chunks` order, for
        # BM25-side period filtering (chunks_v2.json has no fiscal_year column).
        self._chunk_periods: list[tuple[str | None, str | None]] = [
            (_fy_from_source(c["source"]), _quarter_from_source(c["source"]))
            for c in chunks
        ]

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
        fy_filter: bool = True,
    ) -> list[dict]:
        """Return the top *top_k* chunks via RRF over BM25 and dense results.

        Args:
            question: Natural-language query string.
            top_k: Number of chunks to return.
            k: RRF constant controlling rank compression.
            candidates: Number of candidates per leg before fusion.
            fy_filter: When True, restrict both legs to chunks whose fiscal
                year (and quarter, if a single quarter token is present)
                matches the period detected in the question. Skipped when
                the question names no fiscal year.

        Returns:
            List of chunk dicts enriched with bm25_rank, dense_rank, rrf_score.
        """
        penalty = candidates + 1

        target_fy, target_quarter = _detect_period(question) if fy_filter else (None, None)

        # Annual (no-quarter) figures for year Y are commonly restated as the
        # prior-year comparative column in year Y+1's own 10-K MD&A table
        # (e.g. FY2024 gross margin appears in the FY2025 10-K), so a bare
        # single-year question is allowed to match either filing. Quarter
        # questions don't need this: the matching 10-Q already carries its
        # own prior-year comparative inline (see _detect_period).
        allowed_fys: set[str] | None = None
        if target_fy:
            allowed_fys = {target_fy}
            if not target_quarter:
                allowed_fys.add(f"FY{int(target_fy[2:]) + 1}")

        # BM25 leg — mask out chunks from a non-matching fiscal year/quarter
        # before ranking, so period-specific boilerplate from other filings
        # (e.g. every 10-K/10-Q repeats near-identical "Disaggregated Revenue"
        # note text) can't outrank the chunk from the queried period.
        tokens = _tokenize(question)
        bm25_scores = self._bm25.get_scores(tokens)
        if allowed_fys:
            for idx, (chunk_fy, chunk_quarter) in enumerate(self._chunk_periods):
                if chunk_fy not in allowed_fys:
                    bm25_scores[idx] = -np.inf
                elif target_quarter and chunk_quarter != target_quarter:
                    bm25_scores[idx] = -np.inf
        bm25_order = np.argsort(bm25_scores)[::-1][:candidates]
        bm25_ranks: dict[int, int] = {
            int(self._chunks[idx]["id"]): rank
            for rank, idx in enumerate(bm25_order, start=1)
            if bm25_scores[idx] != -np.inf
        }

        # Dense leg — over-request when the period filter is active to
        # compensate for post-filter attrition (a single fiscal year is
        # ~1/10 of chunks; a single quarter within it is smaller still).
        dense_match_count = candidates * 8 if target_quarter else (candidates * 5 if target_fy else candidates)

        query_vec = _encode(question, self._tokenizer, self._onnx_session)
        response = (
            self._supabase.rpc(
                "match_chunks", {"query_embedding": query_vec, "match_count": dense_match_count}
            ).limit(dense_match_count).execute()
        )
        dense_results: list[dict] = response.data

        if allowed_fys:
            dense_results = [
                row for row in dense_results
                if _fy_from_source(row.get("source", "")) in allowed_fys
                and (target_quarter is None or _quarter_from_source(row.get("source", "")) == target_quarter)
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

    logger.info("Loading model (ONNX): %s", MODEL_NAME)
    onnx_path = hf_hub_download(MODEL_REPO, filename="onnx/model.onnx")
    tokenizer_path = hf_hub_download(MODEL_REPO, filename="tokenizer.json")
    tokenizer = Tokenizer.from_file(tokenizer_path)
    onnx_session = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])

    return Retriever(supabase, chunks, tokenizer, onnx_session)
