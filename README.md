# Levi's RAG — AI Due Diligence Copilot

A RAG-powered tool for evidence-tiered analysis of Levi Strauss & Co.'s
SEC filings and strategic narrative. Built as a portfolio project
demonstrating applied AI engineering judgment.

**Status: Week 3 of 5-week build — FastAPI backend, tool router, trend-decay tool, and XBRL KPI tool complete; Next.js frontend next**

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
- [x] Out-of-scope detection — similarity threshold + keyword blocklist, two-stage gate before generation
- [x] FastAPI backend — `POST /query` wrapping retrieve + generate, `GET /health`
- [x] Tool router — heuristic `QuestionType` dispatch (`OUT_OF_SCOPE` → `XBRL_KPI` → `TREND_QUERY` → `FINANCIAL_LOOKUP`)
- [x] Trend-decay tool — Google Trends pull + exponential decay half-life fit for the McLaren collaboration drops
- [x] XBRL KPI tool — direct EDGAR `companyfacts` lookups for revenue, gross profit, operating income, net income, EPS, inventory
- [x] End-to-end integration test — 60-question eval regression (40.0% held) + 5-path dispatch audit
- [ ] Next.js frontend

---

## Tech stack

| Layer | Tool |
|---|---|
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Generation | Gemini 2.5 Flash (via `google-genai`) |
| Vector store | Supabase Postgres + pgvector |
| Retrieval | BM25 (rank_bm25) + pgvector dense, RRF fusion |
| Backend | FastAPI (`app/`) |
| Trend analysis | pytrends (Google Trends) + scipy (`curve_fit`) |
| Frontend (planned) | Next.js + Tailwind on Vercel |
| Data sources | SEC EDGAR full-text filings + EDGAR XBRL `companyfacts` API (both public, no API key required) |

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

**To run a query from the CLI:**
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

## Running the API

```bash
uvicorn app.main:app --reload
```

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What was Levi'\''s FY2025 gross margin?"}'
```

Every response is shaped as:
```json
{
  "question": "...",
  "answer": "...",
  "claims": [{"claim_text": "...", "tier": "...", "supporting_chunk_id": -1, "fiscal_year": null}],
  "chunks": [{"id": 604, "source": "...", "filing_type": "10-K", "section": "...", "fiscal_year": "FY2025", "rrf_score": 0.024, "similarity": 0.544}],
  "out_of_scope": false
}
```

### Tool router

`POST /query` classifies every question into one of four dispatch paths before
doing any retrieval (`app/router.py`, heuristic, no ML — evaluated in this
order, first match wins):

| `QuestionType` | Trigger | What handles it |
|---|---|---|
| `OUT_OF_SCOPE` | Keyword blocklist (competitors, stock price, earnings-call specifics, Dockers) | Declined, no retrieval call |
| `XBRL_KPI` | A KPI term (revenue, gross profit, operating income, net income, EPS, inventory) **and** a period token (FY2025/FY2024/FY2026, Q1–Q4) | `src/xbrl_tool.py` — direct EDGAR XBRL lookup |
| `TREND_QUERY` | Trend-topic keywords (trend, mclaren, f1, silverstone, austin, half-life, search interest, ...) | `src/trend_decay_tool.py` — Google Trends decay analysis |
| `FINANCIAL_LOOKUP` | Default — everything else | Hybrid retrieval (`retrieve.py`) → Gemini tier-tagging (`tier_tagger.py`) |

A second OOS gate runs inside the `FINANCIAL_LOOKUP` path: if the top-1 dense
similarity for the retrieved chunks falls below 0.20, generation is skipped
even if the keyword blocklist didn't catch it.

### XBRL KPI tool

`src/xbrl_tool.py` pulls `https://data.sec.gov/api/xbrl/companyfacts/CIK0000094845.json`
(EDGAR's structured per-fact API, not the filing text) once, caches it to
`data/xbrl_facts.json` (gitignored — regenerate on a fresh checkout), and
resolves a question like *"What was Levi's gross profit in FY2025?"* to a
specific GAAP-tagged value with its filing source and a `Verified-from-filing`
tier.

A real EDGAR data-structure quirk surfaced building this: each 10-K re-tags
up to three years of comparative figures under the *same* `fy`/`fp`/`form`,
all sharing one `"filed"` date — so disambiguating the current-period figure
from prior-year comparatives requires picking the entry with the latest
`"end"` date, not the latest `"filed"` date. A second quirk: Levi's FY2025
10-K tags full-year net income under the GAAP concept `ProfitLoss`, not the
more common `NetIncomeLoss` (which has no annual entries for FY2025/FY2026 in
the cached facts). Both are handled in `KPI_MAP`'s tag-priority lists.

### Trend-decay tool

`src/trend_decay_tool.py` fits an exponential decay curve (`f(t) = A·e^(-λt)`,
via `scipy.optimize.curve_fit`) to Google Trends search interest for
`"Levi's McLaren"` around the two confirmed collaboration drop dates
(Silverstone, July 3 2024; Austin, October 17 2024), and reports a half-life
in weeks against the source report's claimed "6–8 week trend cycle."

**Result:** the search-interest signal for both drops is impulse-like — a
single-week spike followed almost immediately by zero — not a smooth
multi-week decline. The fit is mathematically valid (R²=0.991 for
Silverstone) but a two-point, mostly-zero-separated decay series can't
meaningfully constrain a half-life, so the tool flags both results
`confidence: "low"`. **The report's claim is untestable from Google Trends
weekly data at this granularity — not falsified.** Full methodology, raw
numbers, and the window-normalization issue that motivated the tool's
canonical per-drop windows: [`data/trend_decay_findings.md`](data/trend_decay_findings.md).

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
in top-10; **MISS** = neither. Re-confirmed unchanged at end of Week 3 (`python
src/eval_runner.py` run directly against the retrieval layer, bypassing the
FastAPI router) to verify none of the router/tool-dispatch work introduced a
regression.

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
- **Out-of-scope detection is threshold-tuned, not classifier-based:** the
  similarity gate (0.20) only catches truly empty retrievals; qualitative
  in-scope and OOS questions overlap in the 0.37–0.55 similarity band, so two
  OOS eval questions (CEO earnings call, market share) still score PARTIAL
  rather than being declined outright. The keyword blocklist added in Week 3
  covers known out-of-corpus topics but isn't exhaustive.
- **Trend-decay tool's half-life estimates are low-confidence by design:**
  Google Trends weekly data for the McLaren drops is impulse-like (single-week
  spike, near-zero floor), so both canonical drops are flagged
  `confidence: "low"` regardless of fit R². The source report's "6–8 week
  trend cycle" claim is untestable at this data granularity, not falsified —
  see `data/trend_decay_findings.md`.
- **Same figure, different brand scope, multiple correct answers:** Levi's
  divested Dockers mid-period, so "FY2024 total revenue" has two legitimate
  values depending on whether Dockers is included ($6,355.3M, originally
  reported) or excluded ($6,032.0M / $2,809.1M DTC, restated in the FY2025
  10-K). Both the RAG pipeline and the XBRL tool can return either figure
  depending on which chunk/tag they land on, and neither is wrong — see
  `data/dtc_conflict_finding.md`.
- **Tool router is heuristic, not classifier-based:** `app/router.py` dispatches
  on keyword/regex matching (word-boundary as of Week 3 Task 8), not a trained
  classifier. Misclassifications are possible for unusual phrasings; router
  accuracy improvements are deferred to Week 4–5.

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
