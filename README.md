# Levi's RAG — AI Due Diligence Copilot

A RAG-powered tool for evidence-tiered analysis of Levi Strauss & Co.'s
SEC filings and strategic narrative. Built as a portfolio project
demonstrating applied AI engineering judgment.

**Status: Week 2 of 5-week build — retrieval pipeline and eval harness complete, FastAPI scaffold next**

---

## What this does

Answers natural-language questions about Levi's SEC filings (10-K, 10-Q, 8-K)
with every claim tagged by evidentiary tier:

- `Verified-from-filing` — stated directly in a filing
- `Management-qualitative-statement` — said by management, not a hard number
- `Third-party-benchmark` — sourced from an external report or vendor claim
- `Model-inference` — the system's own calculation or conclusion

Target user: an equity research associate doing single-name diligence on
Levi Strauss & Co. (SEC CIK: 0000094845).

---

## Current state

- [x] EDGAR bulk ingest — 41 filings (3 × 10-K, 7 × 10-Q, 31 × 8-K) from 2024-01-01 onwards
- [x] Section-aware chunking — 1,449 chunks with table detection (`chunk_v2.py`)
- [x] Embeddings — all-MiniLM-L6-v2 (384-dim); 120 financial table chunks re-embedded with metadata prefix to improve dense recall
- [x] Fiscal year metadata — every 10-K/10-Q chunk tagged with `fiscal_year` and `period_of_report` in Supabase
- [x] Supabase live — vectors in Postgres + pgvector; `match_chunks` RPC with IVFFlat index (`probes=10`)
- [x] Hybrid retrieval live — BM25 (rank_bm25) + pgvector dense, fused via RRF (k=60); bug-fixed dense leg, dynamic penalty rank
- [x] Evidentiary tier tagging — Gemini Flash structured output (JSON schema enforced); four tiers, per-claim citations
- [x] End-to-end query pipeline — `query.py` → `retrieve.py` → `tier_tagger.py` → cited, tiered answer
- [x] Hand-labeled eval set — 60 questions across 5 types; recall@10 baseline **40.0%** (24/60 HIT)
- [x] RRF tuning — 6-config grid (k, candidates, FY filter); no improvement found; gap diagnosed as structural
- [ ] FastAPI backend — `/query` endpoint wrapping retrieve + generate
- [ ] Next.js frontend
- [ ] Trend-decay tool (pytrends integration)

---

## Tech stack

| Layer | Tool |
|---|---|
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Generation | Gemini 2.5 Flash (Google AI Studio) |
| Vector store | Supabase Postgres + pgvector |
| Retrieval | BM25 (rank_bm25) + pgvector dense, RRF fusion |
| Backend (planned) | FastAPI |
| Frontend (planned) | Next.js + Tailwind on Vercel |
| Data source | SEC EDGAR (public, no API key required) |

---

## Pipeline

Run each script in order to reproduce the data artifacts:

```bash
python src/ingest.py                   # Fetch 41 filings from EDGAR → data/extracted/
python src/chunk_v2.py                 # Section-aware chunking → data/chunks_v2.json
python src/load_vectors.py             # Embed + upsert all chunks into Supabase
python src/enrich_table_embeddings.py  # Re-embed 120 table chunks with metadata prefix
python src/fix_fiscal_year_metadata.py # Backfill fiscal_year + period_of_report in Supabase
```

`load_vectors.py` downloads ~80 MB on first run (all-MiniLM-L6-v2 model weights).
Requires `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `GEMINI_API_KEY` in `.env`.

**To run a query:**
```bash
python src/query.py "What was Levi's FY2025 gross margin?"
```

**To run the retrieval eval:**
```bash
python src/eval_runner.py                          # Default config (k=60, candidates=100)
python src/eval_runner.py --k 30 --candidates 150  # Custom RRF config
python src/eval_runner.py --fy-filter              # Fiscal-year-filtered dense leg
```

---

## Setup

```bash
git clone https://github.com/sanjay-dilip/levis-rag.git
cd levis-rag
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # Add GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
```

---

## Retrieval performance

Baseline measured on a 60-question hand-labeled eval set (`data/eval_set.json`).
Scoring: **HIT** = any ground-truth chunk in top-10; **PARTIAL** = acceptable chunk
in top-10; **MISS** = neither.

| Metric | Score |
|---|---|
| recall@10 (HIT) | 40.0% (24/60) |
| Partial credit | 23.3% (14/60) |
| Miss | 36.7% (22/60) |

**By question type:**

| Type | Hit | Partial | Miss |
|---|---|---|---|
| numeric_lookup | 15 | 0 | 5 |
| trend_comparison | 4 | 4 | 7 |
| qualitative_lookup | 2 | 5 | 3 |
| inference | 3 | 3 | 4 |
| out_of_scope | 0 | 2 | 3 |

The remaining 36.7% miss rate is a **chunking and metadata problem**, not an RRF
problem. A 6-configuration tuning grid (k ∈ {30, 60, 90}, candidates ∈ {100, 150},
FY filter on/off) found no configuration beats baseline by more than 2pp. Known
failure patterns: income statement continuation chunks displaced by notes tables;
cross-period quarterly queries returning annual data; Risk Factors section outranked
by 10-Q boilerplate. Full tuning results: `data/rrf_tuning_results.md`.

---

## Known limitations

- **8-K exhibit gap:** All 31 8-K files are wrapper documents — earnings release
  financial tables live in Exhibit 99.1 and are not yet ingested. Audited figures
  are present in 10-K/10-Q filings and cover the same data.
- **schema.sql out of sync:** Two columns (`fiscal_year`, `period_of_report`) were
  added via the Supabase SQL editor and are not reflected in `schema.sql`.
- **google-generativeai 0.8.6 deprecated:** Structured output works but migration
  to `google-genai` is deferred until after the FastAPI scaffold.

---

## Data

All data sourced from SEC EDGAR public filings. No proprietary or
non-public data used. Single-company scope: Levi Strauss & Co. only.

---

## Background

Built on top of "The Denim Lifestyle Pivot" — a BUAN 6390 Analytics
Practicum equity research report (Group 7, May 2026) analyzing Levi's
$50M strategic transformation proposal. The tool tests the report's
claims against primary SEC filing evidence.
