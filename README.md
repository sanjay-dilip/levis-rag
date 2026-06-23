# Levi's RAG — AI Due Diligence Copilot

A RAG-powered tool for evidence-tiered analysis of Levi Strauss & Co.'s 
SEC filings and strategic narrative. Built as a portfolio project 
demonstrating applied AI engineering judgment.

**Status: Prototype in progress (Days 1–3 of 5-week build)**

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

- [x] EDGAR 10-K fetch and plain-text extraction (FY2025)
- [ ] Chunking and embeddings
- [ ] Retrieval and cited answer generation (Gemini Flash)
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
| Vector store (prod) | Supabase Postgres + pgvector |
| Backend (prod) | FastAPI |
| Frontend (prod) | Next.js + Tailwind on Vercel |
| Data source | SEC EDGAR (public, no API key required) |

---

## Setup

```bash
git clone https://github.com/yourusername/levis-rag.git
cd levis-rag
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env         # Add your GEMINI_API_KEY
```

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
