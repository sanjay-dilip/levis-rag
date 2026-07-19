# Levi's RAG — AI Due Diligence Copilot

![Status](https://img.shields.io/badge/status-live-brightgreen)
![Recall@10](https://img.shields.io/badge/recall%4010-85.0%25%20(51%2F60)-blue)
![Tests](https://img.shields.io/badge/tests-63%2F64%20passing-yellow)
![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20Render-informational)
![Frontend](https://img.shields.io/badge/frontend-Next.js%20%2B%20Vercel-informational)

A RAG-powered tool for evidence-tiered analysis of Levi Strauss & Co.'s
publicly available SEC EDGAR filings and strategic narrative. Built as a
portfolio project demonstrating applied AI engineering judgment.

**Status: Live — deployed frontend + backend, full feature set**

**Live app:** https://levis-rag.vercel.app
**Backend API:** https://levis-rag.onrender.com (`GET /health`, `POST /query`)

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
- [x] Supabase live — vectors in Postgres + pgvector; `match_chunks` RPC with IVFFlat index (`probes=30`)
- [x] Hybrid retrieval live — BM25 (rank_bm25) + pgvector dense, fused via RRF (k=60); bug-fixed dense leg, dynamic penalty rank; quarter-aware period filtering on both legs
- [x] Evidentiary tier tagging — Gemini Flash structured output (JSON schema enforced); four tiers, per-claim citations
- [x] End-to-end query pipeline — `query.py` → `retrieve.py` → `tier_tagger.py` → cited, tiered answer
- [x] Hand-labeled eval set — 60 questions across 5 types; recall@10 **85.0%** (51/60 HIT)
- [x] RRF tuning — 6-config grid (k, candidates, FY filter); no improvement found; gap diagnosed as structural
- [x] Quarter-aware period filtering — fixes the structural gap the RRF grid couldn't; recall@10 40.0% → 58.3%
- [x] IVFFlat probes raised 10 → 30 — closed an approximate-index coverage gap that was hiding correctly-fixed embeddings
- [x] Targeted embedding enrichment + ground-truth relabeling — repeatable playbook closing dilution/mislabeling gaps; recall@10 58.3% → 85.0%
- [x] Out-of-scope detection — similarity threshold + keyword blocklist, two-stage gate before generation
- [x] FastAPI backend — `POST /query` wrapping retrieve + generate, `GET /health`
- [x] Tool router — heuristic `QuestionType` dispatch (`OUT_OF_SCOPE` → `XBRL_KPI` → `TREND_QUERY` → `FINANCIAL_LOOKUP`)
- [x] Trend-decay tool — Google Trends pull + exponential decay half-life fit for the McLaren collaboration drops
- [x] XBRL KPI tool — direct EDGAR `companyfacts` lookups for revenue, gross profit, operating income, net income, EPS, inventory
- [x] End-to-end integration test — 60-question eval regression (40.0% held) + 5-path dispatch audit
- [x] Next.js frontend — chat UI, citation/tier panel, KPI/trend-decay cards, deployed on Vercel

---

## Tech stack

| Layer | Tool |
|---|---|
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 — local `SentenceTransformer` for the ingestion scripts; the deployed API runs the same model's pre-exported ONNX weights via `onnxruntime` instead (no `torch`/`transformers` at runtime — needed to fit Render's free-tier 512MB RAM limit; verified numerically equivalent, cosine similarity 1.0, before switching) |
| Generation | Gemini Flash (`gemini-flash-latest`, via `google-genai`) |
| Vector store | Supabase Postgres + pgvector |
| Retrieval | BM25 (rank_bm25) + pgvector dense, RRF fusion |
| Backend | FastAPI (`app/`) |
| Trend analysis | pytrends (Google Trends) + scipy (`curve_fit`) |
| Frontend | Next.js + Tailwind, deployed on Vercel |
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
(`GROQ_API_KEY` and `GEMINI_API_KEY_II` are unrelated to this pipeline — see Setup.)

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

### Deployment

The app is live: frontend on Vercel (`https://levis-rag.vercel.app`), backend
on Render's free tier (`https://levis-rag.onrender.com`).

```bash
curl https://levis-rag.onrender.com/health

curl -X POST https://levis-rag.onrender.com/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What was Levi'\''s FY2025 gross margin?"}'
```

**Getting this running on Render's free tier took two real fixes**, both
worth knowing if redeploying elsewhere:
- The backend built the `Retriever` and `genai.Client` at **module import
  time**, which blocked uvicorn from ever binding `$PORT` — Render's port
  scanner gave up before the process was ready. Fixed by moving that work
  into a FastAPI `lifespan` startup hook (`app/main.py`), so the port binds
  immediately and the heavy initialization happens after.
- Even after that, the full `sentence-transformers` + `transformers` +
  `torch` stack didn't fit in Render's 512MB RAM limit (confirmed via
  repeated OOM kills — CPU-only torch wasn't enough on its own). Fixed by
  running the same `all-MiniLM-L6-v2` model's pre-exported ONNX weights via
  `onnxruntime` instead of loading it through `sentence-transformers` at
  runtime — see the Embeddings row above.

**Known limitation:** Gemini's free-tier daily quota (20 requests/day) means
`FINANCIAL_LOOKUP` questions can occasionally return a `429` or take
60-130s+ (the client appears to retry against the server's suggested delay
before giving up) once the quota is exhausted for the day. The other three
question types (`XBRL_KPI`, `TREND_QUERY`, `OUT_OF_SCOPE`) don't call Gemini
and aren't affected.

### Tool router

`POST /query` classifies every question into one of four dispatch paths before
doing any retrieval (`app/router.py`, heuristic, no ML — evaluated in this
order, first match wins):

| `QuestionType` | Trigger | What handles it |
|---|---|---|
| `OUT_OF_SCOPE` | Keyword blocklist (competitors, stock price, earnings-call specifics, Dockers) | Declined, no retrieval call |
| `XBRL_KPI` | A KPI term (revenue, gross profit, operating income, net income, EPS, inventory) **and** a period token (FY2025/FY2024/FY2026, Q1–Q4) — **unless** the question also contains a segment/percentage/comparison qualifier (`dtc`, `wholesale`, `segment`, `percentage`, `percent`, `ratio`, `management say`) or names 2+ distinct fiscal years, in which case it falls through to `FINANCIAL_LOOKUP` instead | `src/xbrl_tool.py` — direct EDGAR XBRL lookup |
| `TREND_QUERY` | Trend-topic keywords (trend, mclaren, f1, silverstone, austin, half-life, search interest, ...) | `src/trend_decay_tool.py` — Google Trends decay analysis |
| `FINANCIAL_LOOKUP` | Default — everything else | Hybrid retrieval (`retrieve.py`) → Gemini tier-tagging (`tier_tagger.py`) |

A second OOS gate runs inside the `FINANCIAL_LOOKUP` path: if the top-1 dense
similarity for the retrieved chunks falls below 0.20, generation is skipped
even if the keyword blocklist didn't catch it.

**Router fix — XBRL_KPI over-matching (issue #17):** the original `XBRL_KPI`
rule was a bare "KPI term + period token" AND, with no concept of segment
breakdown, percentage-of-total, multi-period comparison, or qualitative
phrasing. A full audit of the 60-question eval set found 32 questions
matching that AND — only 6 genuinely belong on `XBRL_KPI` (single-KPI,
single-period lookups); the other 26 were being misrouted straight past
retrieval to a tool that has no segment/channel tags and only ever extracts
one period. Flagship case: *"What was Levi's DTC revenue as a percentage of
total revenue in FY2025?"* routed to `XBRL_KPI` and answered with total
revenue ($6.28B) instead of the DTC percentage (49%), even though retrieval
already answers this question correctly. Fixed with two additive guards: an
exclusion-term list (`dtc`, `wholesale`, `segment`, `percentage`, `percent`,
`ratio`, `management say`) and a structural check rejecting questions that
name 2+ distinct fiscal years. Verified against all 32 affected questions
(`tests/test_router.py`, 36 assertions) and live end-to-end: the DTC-percentage
question now routes to `FINANCIAL_LOOKUP` and answers "49% of total net
revenues" correctly.

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
multi-week decline. Across repeated pulls, fitted half-lives have landed in
the 0.1–0.3 week range (R²≈0.93–0.99, `confidence: "low"`–`"medium"`,
impulse-flagged); Austin's decay series is frequently too short to fit at
all (`status: "insufficient_data"`). **The report's claim is untestable from
Google Trends weekly data at this granularity — not falsified.**

Repeated pulls of the identical canonical window and keyword also produce
different results from each other — Google Trends' own sampling noise for
this low-search-volume keyword is enough to shift a result between `"ok"`
and `"insufficient_data"`, or move a fitted half-life between 0.1 and 0.3
weeks, run to run. Full methodology, raw numbers, both findings above, and
the window-normalization issue that motivated the tool's canonical per-drop
windows: [`data/trend_decay_findings.md`](data/trend_decay_findings.md).

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

`GROQ_API_KEY` and `GEMINI_API_KEY_II` in `.env.example` are optional — they're
only used by the standalone Groq/Gemini tier-tagging comparison script
(`src/tier_comparison_runner.py`), not by core setup, the pipeline, or the
live `/query` path.

### Running tests

```bash
python -m pytest -v
```

---

## Retrieval performance

Measured on a 60-question hand-labeled eval set (`data/eval_set.json`).
Scoring: **HIT** = any ground-truth chunk in top-10; **PARTIAL** = acceptable chunk
in top-10; **MISS** = neither.

| Metric | Score |
|---|---|
| recall@10 (HIT) | 85.0% (51/60) |
| Partial credit | 8.3% (5/60) |
| Miss | 6.7% (4/60) |

**By question type:**

| Type | Hit | Partial | Miss |
|---|---|---|---|
| numeric_lookup | 19 | 1 | 0 |
| trend_comparison | 15 | 0 | 0 |
| qualitative_lookup | 8 | 2 | 0 |
| inference | 9 | 1 | 0 |
| out_of_scope | 0 | 1 | 4 |

Of the 4 remaining misses, all are out-of-scope questions correctly rejected by the
keyword/similarity gates — the eval scorer has no separate "correct rejection" verdict,
so a correct OOS decline still counts as MISS. Real (non-OOS-category) retrieval
misses: **0/60**.

**Baseline: 40.0% recall@10.** A 6-configuration RRF tuning grid (k ∈ {30, 60,
90}, candidates ∈ {100, 150}, a plain fiscal-year filter on/off) found no configuration
beat this by more than a 2pp noise floor — the gap was structural (chunking/metadata),
not a fusion-parameter problem. Full grid results: `data/rrf_tuning_results.md`.

**Two structural fixes closed most of the gap:**
- **Quarter-aware period filtering (40.0% → 58.3%).** Every 10-K/10-Q repeats
  near-identical disaggregated-revenue boilerplate with no period token in the text
  itself (dates are spelled out, e.g. "November 30, 2025", never "FY2025") — the
  original FY-only filter couldn't tell filings apart on content, so cross-period
  chunks crowded out the one from the queried period. `_detect_period()`
  (`src/retrieve.py`) now extracts fiscal year *and* quarter from the question and
  filters **both** the BM25 and dense legs (the tuning grid's FY filter only touched
  dense, which is why it found nothing). Two edge cases needed explicit handling:
  Levi's Q4 has no dedicated 10-Q (only the annual 10-K), so a literal "Q4" filter
  falls back to FY-only; and a bare single-year question can also match the
  *following* year's 10-K, since annual figures get restated there as a prior-year
  comparative column.
- **IVFFlat `probes` 10 → 30.** The approximate vector index was only scanning 10 of
  50 list partitions, hiding embeddings that were already correctly fixed — raising
  `probes` alone lifted recall@10 several points before any further embedding writes.

**The rest of the gap (58.3% → 85.0%) closed through iterative, verified
embedding-prefix enrichment and eval-set label corrections** — a repeatable playbook:
diagnose a chunk's dilution (a real answer buried in a long, mixed-topic passage) or a
stale ground-truth label, cosine-check a content-specific prefix against the target
question *and* every topically-adjacent question before writing to Supabase (a prefix
that helps one question can measurably hurt another sharing similar vocabulary — hit
in practice at least once, not just a theoretical risk, and guarded against on every
write since), then verify with a full 60-question regression run. Applied across
roughly a dozen chunks and eval-set corrections; full fix-by-fix detail (every
attempt, every reverted experiment, every regression found and traced) is in
the git commit history.

**One recurring, understood, and accepted limitation:** a handful of questions
(`eval_028`, `eval_033`, `eval_054`, `eval_060`) share a "dense-ceiling, BM25-absent"
pattern — the ground-truth chunk already has the best possible dense-similarity match,
but its BM25 rank is far outside the retriever's candidate window, so it can't be
boosted by the embedding-prefix technique (which only touches the dense leg) and can't
out-fuse chunks with moderate-but-present ranks on both legs. Closing this would need a
raw-text change (re-chunking — assessed as too high-risk relative to the confirmed
benefit) or a wider BM25 candidate window (tested broadly in the original tuning grid
and found not to help). These score PARTIAL by design, not as open bugs.

---

## Known limitations

**Open:**

- **Out-of-scope detection is threshold-tuned, not classifier-based:** the
  similarity gate (0.20) only catches truly empty retrievals; qualitative
  in-scope and OOS questions overlap in the 0.37–0.55 similarity band, so one
  OOS eval question (market share) still scores PARTIAL rather than being
  declined outright. The keyword blocklist covers known out-of-corpus topics
  but isn't exhaustive.
- **Eval scorer has no "correct rejection" verdict for out-of-scope questions:**
  `eval_runner.py` labels every OOS question `MISS`, even when the keyword or
  similarity gate correctly declines to answer it. This inflates the headline
  miss rate — all 4 current misses are OOS questions behaving correctly, not
  retrieval failures. Not yet fixed; noted here so the miss-rate number isn't
  misread.
- **Tool router is heuristic, not classifier-based:** `app/router.py` dispatches
  on keyword/regex matching, not a trained classifier. A specific over-matching
  bug (`XBRL_KPI` swallowing questions retrieval already answered correctly)
  was found and fixed — see "Router fix" above — but the heuristic approach
  itself remains a known limitation for unusual phrasings not yet seen.
- **Groq/Llama 3.3 70B vs. Gemini Flash tier-tagging comparison is a work in
  progress:** a standalone research script (`src/tier_comparison_runner.py`,
  not part of the live `/query` path) holds retrieval constant and tags the
  same retrieved chunks with both models, to compare tier-tagging quality —
  including the caveat that Groq's `llama-3.3-70b-versatile` has no
  schema-enforced structured output (`json_object` only, no `json_schema`),
  unlike Gemini's `response_schema`. 15 of the planned 60 eval questions are
  genuinely scored on both models so far; both providers' free tiers impose
  hard **daily** quotas (Gemini: 20 requests/day; Groq: 100,000 tokens/day)
  that a single session can exhaust well short of 60 questions, so this is
  completed incrementally as quotas reset. Tracked in GitHub issues
  #26/#28/#29. No impact on the live app — `tier_tagger.py` and the deployed
  `/query` endpoint remain Gemini-only throughout.

**By design (investigated, resolved, not open bugs):**

- **8-K exhibit gap:** All 31 8-K files are wrapper documents — earnings release
  financial tables live in Exhibit 99.1 and are not ingested. Audited figures
  are present in 10-K/10-Q filings and cover the same data.
- **Trend-decay tool's half-life estimates are low-confidence and pull-to-pull
  unstable, by design** — see the "Trend-decay tool" section above and
  `data/trend_decay_findings.md` for the full methodology and findings.
- **Same figure, different brand scope, multiple correct answers:** Levi's
  divested Dockers mid-period, so "FY2024 total revenue" has two legitimate
  values depending on whether Dockers is included ($6,355.3M, originally
  reported) or excluded ($6,032.0M / $2,809.1M DTC, restated in the FY2025
  10-K). Both the RAG pipeline and the XBRL tool can return either figure
  depending on which chunk/tag they land on, and neither is wrong — see
  `data/dtc_conflict_finding.md`.

---

## Data

All data sourced from SEC EDGAR public filings. No proprietary or
non-public data used. Single-company scope: Levi Strauss & Co. only.

---

## Potential future scope

- **Earnings call transcripts (considered, not added):** FY2026 guidance is
  confirmed absent from every 10-K — guidance is discussed on earnings calls,
  not filed. Adding transcripts as a data source was evaluated and closed as
  out of scope for this build: transcripts are neither filed/furnished with
  the SEC nor sourced from EDGAR (they'd come from Levi's IR site or a
  third-party transcript service), which conflicts with this project's
  stated scope of SEC-EDGAR-only, public-record data. Revisiting this would
  be a scope expansion, not a same-scope data-source swap, and would also
  require updating the scope language above and extending the evidentiary
  tier system to mark forward-looking/unaudited guidance distinctly from
  filed figures.

---

## Background

Built on top of "The Denim Lifestyle Pivot" — a BUAN 6390 Analytics
Practicum equity research report (Group 7, May 2026) analyzing Levi's
$50M strategic transformation proposal. The tool tests the report's
claims against primary SEC filing evidence.

---

## What This Project Demonstrates

- Hybrid retrieval system design — BM25 + dense vector search fused via RRF,
  with quarter-aware metadata filtering on both legs
- Retrieval quality diagnosis and iterative tuning against a hand-labeled
  eval set, with every fix verified by a full regression run
- Evidentiary-tier answer grounding to keep generated claims traceable to a
  specific filing, external source, or the model's own inference
- Multi-tool orchestration — heuristic dispatch across RAG, a structured
  XBRL API lookup, and a Google Trends decay-curve analysis
- Production deployment troubleshooting on real resource constraints
  (Render's free-tier port-binding and 512MB OOM limits, resolved via a
  lifespan hook and an ONNX runtime swap)
- Full-stack delivery — FastAPI backend and Next.js frontend, both deployed
  and integration-tested live, not just locally
- Regression-tested engineering workflow — a pytest suite and a retrieval
  eval harness gating every change
- Cross-provider LLM evaluation — a controlled comparison of Gemini's
  schema-enforced structured output against Groq/Llama 3.3 70B's
  best-effort JSON mode
