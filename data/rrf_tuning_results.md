# RRF Tuning Results — Week 2, Task 7

Systematic grid search over RRF k, candidate pool size, and fiscal-year
dense-leg filtering. Evaluated against the full 60-question eval set.
Baseline to beat: **40.0% hit rate** (24/60).

---

## Results Table

| Run | k  | Candidates | FY Filter | Hit%  | Partial% | Miss% | vs Baseline |
|-----|----|------------|-----------|-------|----------|-------|-------------|
| A   | 60 | 100        | No        | 40.0  | 23.3     | 36.7  | —           |
| B   | 30 | 100        | No        | 36.7  | 20.0     | 43.3  | -3.3pp      |
| C   | 90 | 100        | No        | 40.0  | 23.3     | 36.7  | 0.0pp       |
| D   | 30 | 150        | No        | 36.7  | 21.7     | 41.7  | -3.3pp      |
| E   | 60 | 150        | No        | 40.0  | 23.3     | 36.7  | 0.0pp       |
| F   | 60 | 100        | Yes       | 40.0  | 23.3     | 36.7  | 0.0pp       |

---

## By Question Type — Best Run (A/C/E/F all tied at 40.0%, Run A shown)

| Question Type       | Hit | Partial | Miss |
|---------------------|-----|---------|------|
| inference           | 3   | 3       | 4    |
| numeric_lookup      | 15  | 0       | 5    |
| out_of_scope        | 0   | 2       | 3    |
| qualitative_lookup  | 2   | 5       | 3    |
| trend_comparison    | 4   | 4       | 7    |

**Note — FY filter distribution shift (Run F vs Run A):**
The FY filter does not change overall hit% but shifts the distribution:
- inference: +1 Hit, +1 Partial, -2 Miss (improves)
- numeric_lookup: -1 Hit, +1 Partial (loses a hit, gains a partial)
- qualitative_lookup: 0 Hit, -2 Partial, +2 Miss (worsens)
- trend_comparison: 0 Hit, +1 Partial, -1 Miss (marginal improvement)

Net effect: zero. The FY filter helps inference but harms qualitative_lookup
equally. Not worth enabling by default.

---

## Conclusion

No configuration beats 40.0% by more than 2 percentage points. The grid
result is conclusive:

**The remaining retrieval gap is a chunking and metadata problem, not an
RRF problem.**

Specific failure modes identified (unchanged from pre-tuning analysis):
- Income statement continuation chunks (601, 602) — consistently displaced
  by Notes disaggregated revenue tables (686, 453, 208) which score higher
  on both BM25 and dense legs for any revenue/channel query.
- Business-section DTC % figures (596, 603) — not surfaced for "DTC
  percentage" queries. BM25 keyword overlap is weak vs MD&A narrative chunks.
- Risk Factors section (536, 538) — retriever returns 10-Q boilerplate
  instead of 10-K Item 1A content.
- Cross-period quarterly comparisons — wrong fiscal year's notes surface
  because annual 10-K notes dominate keyword and semantic space.

These are structural retrieval failures. Remedies belong in a separate fix
pass (metadata filtering at query time, section-type routing, or re-chunking
the income statement tables) after the FastAPI scaffold is built.

**Winning configuration: k=60, candidates=100, fy_filter=False (unchanged
from Week 1 defaults). Official recall@10 baseline remains 40.0% (24/60).**
