# Trend Decay Findings — Levi's McLaren Google Trends Analysis

> Source: `src/trend_diagnostic.py` (Task 4) and `src/trend_decay_tool.py` (Tasks 5–6).
> Subject: the BUAN 6390 report's claim of a "6–8 week trend cycle" for social
> interest around the Levi's × McLaren collaboration drops.

## Method

1. Pulled Google Trends `interest_over_time()` via `pytrends` (`hl='en-US', tz=360`) for the keyword `"Levi's McLaren"` around two confirmed drop dates:
   - **Silverstone / British Grand Prix** — July 3, 2024
   - **Austin / U.S. Grand Prix** — October 17, 2024
2. Google Trends auto-selects response granularity by requested window length (native weekly only above ~269 days). All windows used here are shorter, so raw responses came back **daily** and were resampled to weekly (mean per ISO week, `W-MON` buckets) before any analysis.
3. Located the peak value in `[drop_date, drop_date + 21 days]`.
4. Extracted the decay series from the peak forward, truncated at the first run of 3 consecutive zero weeks.
5. Fit `f(t) = A * exp(-λt)` (t = weeks since peak) via `scipy.optimize.curve_fit`, computed `half_life = ln(2) / λ` and R².
6. Flagged any decay series with ≤2 non-zero weeks after the peak as **impulse-like** — a step function, not a decay curve — and forced `confidence: low` regardless of R².

## Finding 1 — Window-dependent renormalization (discovered in Task 5)

Google Trends normalizes relative interest (0–100) to the **peak within the requested window**, not to any absolute search-volume scale. This means the same underlying search activity produces different reported values depending on what window it's compared against:

| Window pulled | Austin week-of-2024-10-21 value |
|---|---|
| 2024-05-01 → 2024-12-31 (full Task 4 diagnostic window, dominated by the much larger Silverstone spike) | 2.3 |
| 2024-09-01 → 2024-12-31 (Task 5 test window) | 20.9 |
| 2024-09-15 → 2024-12-15 (Task 6 canonical window, `KNOWN_DROPS["austin_2024"]`) | 27.6 |

The same Austin search activity looks negligible, moderate, or strong purely as a function of what else is in the comparison window. **Implication:** any cross-event comparison ("Austin had less interest than Silverstone") must control for window choice, or it is comparing normalization artifacts, not search volume. `src/trend_decay_tool.py` now fixes a canonical, drop-isolated window per event (`KNOWN_DROPS`) specifically to make `analyze_drop()` results window-stable and reproducible across calls.

## Finding 2 — Raw data and curve fit results

### Silverstone drop (canonical window: 2024-06-01 → 2024-09-01)

Weekly series (`"Levi's McLaren"`):

| Week of | Value |
|---|---|
| 2024-06-03 | 0.0 |
| 2024-06-10 | 0.0 |
| 2024-06-17 | 0.0 |
| 2024-06-24 | 0.0 |
| 2024-07-01 | 23.0 |
| **2024-07-08** | **35.7  (peak)** |
| 2024-07-15 | 0.0 |
| 2024-07-22 | 0.0 |
| 2024-07-29 | 3.0 |
| 2024-08-05 | 0.0 |
| 2024-08-12 | 0.0 |
| 2024-08-19 | 0.0 |
| 2024-08-26 | 2.3 |
| 2024-09-02 | 0.0 |

Decay series used for fitting (peak forward, truncated at the first 3-consecutive-zero run): **`[35.7, 0.0, 0.0, 3.0, 0.0]`** (5 points, 2 non-zero).

| Metric | Value |
|---|---|
| Peak value | 35.7 (week of 2024-07-08) |
| Decay series length | 5 weeks |
| Non-zero weeks in decay series | 2 |
| R² | **0.991** |
| Fitted half-life | **0.1 weeks (1 day)** |
| Confidence | **low** (impulse override) |
| vs. report claim (3–4 week half-life) | shorter |

### Austin drop (canonical window: 2024-09-15 → 2024-12-15)

Decay series used for fitting: **`[27.6, 0.0, 12.0, 0.0]`** (4 points, 2 non-zero).

| Metric | Value |
|---|---|
| Peak value | 27.6 (week of 2024-10-21) |
| Decay series length | 4 weeks |
| Non-zero weeks in decay series | 2 |
| R² | 0.720 |
| Fitted half-life | 0.1 weeks (1 day) |
| Confidence | **low** (impulse override) |
| vs. report claim (3–4 week half-life) | shorter |

## Finding 3 — The R² signal: a valid fit to an unfittable shape

For Silverstone, **R² = 0.991 is a high-quality fit** in the strict mathematical sense — the exponential curve passes very close to the five data points. But the data points are `[35.7, 0, 0, 3.0, 0]`: a single-week spike followed almost immediately by a floor at (or near) zero, not a smooth multi-week decline. A curve that drops from 35.7 to near-zero in one step is fit just as well by `λ → ∞` (instant decay) as by any other steep curve — there is no information in two non-zero points, three weeks apart, that constrains where between "fast" and "very fast" the true decay rate sits. The high R² measures *fit quality against this exact decay model*, not *evidence that the decay model is the right description of the underlying process*. That's why `src/trend_decay_tool.py` treats ≤2 non-zero post-peak weeks as impulse-like and forces `confidence: low` independent of R² — R² alone would otherwise overstate certainty.

**Conclusion: this is "untestable," not "falsified."** Google Trends weekly data for `"Levi's McLaren"` produces an impulse-like signal around the Silverstone drop — single-week spike to 35.7, immediate floor. The exponential decay fit is mathematically valid (R²=0.991) but the resulting half-life estimate (0.1 weeks) is not meaningful: it reflects two data points spaced apart by mostly-zero weeks, not an observed multi-week decline. The signal structure does not support the decay model in the first place; weekly granularity is fundamentally insufficient to resolve a sub-week decay process even if one exists. The report's "6–8 week trend cycle" claim is **untestable from this data source at this granularity** — the data cannot confirm it, and it also cannot rule it out, because nothing in a single-week impulse constrains a multi-week hypothesis either way. This is a distinct conclusion from "falsified," which would require decay data dense and multi-week enough to show a measured half-life that contradicts the claimed range. No such evidence exists here.

## What would resolve this

- **Daily-resolution Google Trends data** (available natively for windows ≤90 days) pulled in the days immediately following each drop, rather than weekly-resampled data, to actually resolve whether the decay happens within days (consistent with this impulse pattern) or is being aliased by the weekly bucketing.
- **A higher-volume keyword or a platform with finer relative-volume resolution** — `"Levi's McLaren"` search volume may simply be too low for Google Trends' relative-normalization scheme to expose a smooth decay curve at any granularity.
- **A direct engagement metric** (social post impressions/engagement over time, sell-through velocity) rather than search interest as a proxy, since the report's underlying claim is about social/commercial trend decay, not search-query decay specifically.
