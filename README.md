# Levi's RAG — AI Due Diligence Copilot

A RAG-powered tool for evidence-tiered analysis of Levi Strauss & Co.'s 
SEC filings and strategic narrative. Built as a portfolio project 
demonstrating applied AI engineering judgment.

**Status: Prototype in progress (Days 1–5 of 5-week build)**

---

## What this does

Answers natural-language questions about Levi's SEC filings (10-K, 10-Q, 8-K)
with every claim tagged by evidentiary tier:

- `Verified-from-filing` — stated directly in a filing
- `Management-qualitative-statement` — said by management, not a hard number
- `Third-party-benchmark` — sourced from an external report or vendor claim
- `Model-inference` — the system's own inference

Target user: an equity research associate doing single-name diligence on 
Levi Strauss & Co. (SEC CIK: 0000094845).

---

## Current state

- [x] EDGAR bulk ingest — 41 filings (3 × 10-K, 7 × 10-Q, 31 × 8-K) from 2024-01-01 onwards
- [x] Section-aware chunking — 1,449 chunks with table detection (`chunk_v2.py`)
- [x] Embeddings — all-MiniLM-L6-v2 (384-dim), 1,449 vectors
- [x] Supabase live — vectors stored in Postgres + pgvector, `match_chunks` RPC ready
- [x] Hybrid retrieval live — BM25 (rank_bm25) + pgvector dense, fused via RRF (`retrieve.py`)
- [x] End-to-end query pipeline — `query.py` calls `retrieve.py` → Gemini Flash → cited answer
- [ ] Evidentiary tier tagging
- [ ] Evidentiary tier tagging
- [ ] FastAPI backend + tool router
- [ ] Next.js frontend
- [ ] Trend-decay tool (pytrends, McLaren/F1 drops)
- [ ] Hand-labeled eval set (50–100 Q&A pairs)

---

## Tech stack

| Layer | Tool |
|---|---|
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Generation | Gemini Flash (Google AI Studio) |
| Vector store | Supabase Postgres + pgvector ✓ live |
| Backend (prod) | FastAPI |
| Frontend (prod) | Next.js + Tailwind on Vercel |
| Data source | SEC EDGAR (public, no API key required) |

---

## Pipeline

Run each script in order to reproduce the data artifacts:

```bash
python src/ingest.py        # Fetch 41 filings from EDGAR → data/extracted/
python src/chunk_v2.py      # Section-aware chunking → data/chunks_v2.json
python src/load_vectors.py  # Embed + upsert all chunks into Supabase
```

`load_vectors.py` downloads ~80 MB on first run (all-MiniLM-L6-v2 model weights).
Requires `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `GEMINI_API_KEY` in `.env`.

---

## Setup

```bash
git clone https://github.com/yourusername/levis-rag.git
cd levis-rag
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # Add GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
```

---

## Known limitations

**Financial table retrieval (Week 2 fix):** Table chunks embed poorly in dense space
(cosine scores 0.11–0.20), so they rank near the bottom of the dense leg and get
surfaced only when BM25 keyword matching happens to fire. The fix planned for Week 2
is to enrich each table chunk's text with its section header and filing metadata
(e.g. `"FY2025 10-K | Item 7. MD&A | [table rows]"`) before re-embedding — rather
than tuning RRF constants, which only moves the problem around.

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
