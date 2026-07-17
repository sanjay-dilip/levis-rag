# Trend Decay Findings — Levi's McLaren Google Trends Analysis

> Source: `src/trend_diagnostic.py` (Task 4) and `src/trend_decay_tool.py` (Tasks 5–6).
> Subject: the BUAN 6390 report's ("The Denim Lifestyle Pivot," Group 7, May 2026)
> claim of a "6–8 week trend cycle" for social interest around the Levi's ×
> McLaren collaboration drops.

## Headline finding, stated plainly

**Every single Google Trends pull taken of these two drops — across five independent
measurements spanning Week 3 through this write-up — has produced a half-life estimate
of well under one week (0.1–0.3 weeks), not the 3–4 weeks implied by the report's
"6–8 week trend cycle" claim.** That consistent shortfall is real and worth stating
plainly. But the honest conclusion is **not** "the report's claim is wrong." It is:
**at weekly Google Trends granularity, this data source cannot distinguish a genuine
multi-week decay from a single-week impulse-then-floor artifact — the claim is
untestable here, not falsified.** The reasoning for that distinction is the core
intellectual-honesty point of this whole analysis and is laid out in full below
(see "Finding 3" and "Why untestable, not falsified").

A second, independently-confirmed finding compounds the first: **repeated pulls of
the identical canonical window and keyword return materially different numbers**
(see "Finding 4" below) — this is not a data source stable enough to pin a single
"the" half-life number on in the first place, let alone one precise enough to
adjudicate a specific week-count claim.

## Method

1. Pulled Google Trends `interest_over_time()` via `pytrends` (`hl='en-US', tz=360`) for the keyword `"Levi's McLaren"` around two confirmed drop dates:
   - **Silverstone / British Grand Prix** — July 3, 2024
   - **Austin / U.S. Grand Prix** — October 17, 2024
2. Google Trends auto-selects response granularity by requested window length (native weekly only above ~269 days). All windows used here are shorter, so raw responses came back **daily** and were resampled to weekly (mean per ISO week, `W-MON` buckets) before any analysis.
3. Located the peak value in `[drop_date, drop_date + 21 days]`.
4. Extracted the decay series from the peak forward, truncated at the first run of 3 consecutive zero weeks (`ZERO_RUN_LENGTH = 3`). If fewer than `MIN_DECAY_SERIES_LENGTH = 3` points survive, or the peak window itself is empty/zero, the result is `status: "insufficient_data"` — no fit is attempted.
5. Fit `f(t) = A * exp(-λt)` (t = weeks since peak) via `scipy.optimize.curve_fit`, computed `half_life = ln(2) / λ` and R².
6. Flagged any decay series with ≤2 non-zero weeks after the peak (`IMPULSE_MAX_NONZERO_WEEKS = 2`) as **impulse-like** — a step function, not a decay curve — and forced `confidence: low` regardless of R².

**Single data source, by MVP scope.** Only Google Trends search-interest data was used. No corroborating signal — social post engagement/impression volume, sell-through or POS data, or any other independent measure of "trend interest" — was in scope for this build. This matters directly: the report's underlying claim is about social/commercial trend decay broadly, and search-query interest is one proxy for that, not a direct measurement of it. See "Limitations" below.

## Finding 1 — Window-dependent renormalization (discovered in Task 5)

Google Trends normalizes relative interest (0–100) to the **peak within the requested window**, not to any absolute search-volume scale. This means the same underlying search activity produces different reported values depending on what window it's compared against:

| Window pulled | Austin week-of-2024-10-21 value |
|---|---|
| 2024-05-01 → 2024-12-31 (full Task 4 diagnostic window, dominated by the much larger Silverstone spike) | 2.3 |
| 2024-09-01 → 2024-12-31 (Task 5 test window) | 20.9 |
| 2024-09-15 → 2024-12-15 (Task 6 canonical window, `KNOWN_DROPS["austin_2024"]`) | 27.6 |

The same Austin search activity looks negligible, moderate, or strong purely as a function of what else is in the comparison window. **Implication:** any cross-event comparison ("Austin had less interest than Silverstone") must control for window choice, or it is comparing normalization artifacts, not search volume. `src/trend_decay_tool.py` now fixes a canonical, drop-isolated window per event (`KNOWN_DROPS`) specifically to make `analyze_drop()` results window-stable and reproducible across calls — Finding 4 below shows this fixed-window control is necessary but not sufficient for reproducibility.

## Finding 2 — Original raw data and curve fit results (Week 3, Tasks 5–6)

### Silverstone drop (canonical window: 2024-06-01 → 2024-09-01)

Weekly series (`"Levi's McLaren"`) as originally pulled:

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

## Finding 4 — Pull-to-pull instability (discovered assembling this write-up)

Assembling this document required confirming the exact, already-verified numbers directly from `CONTEXT.md` before writing anything down. Doing that surfaced a real discrepancy: the original Task 5/6 diagnostic numbers above (Silverstone R²=0.991/half-life 0.1wk; Austin R²=0.720/half-life 0.1wk, `status: "ok"`) do **not** match what every live-app verification since (Week 4's T5.6 through the later T7 re-verification sessions) has consistently reported: Silverstone half-life **0.3 weeks**, R²≈0.99, confidence **medium**; Austin `status: "insufficient_data"`.

This was investigated by re-running `analyze_drop()` for both canonical windows fresh (not a new diagnostic, the same existing tool against the same existing canonical windows) rather than assuming either number set was still current:

| Pull | Silverstone peak / half-life / R² / confidence | Austin peak / half-life / R² / confidence / status |
|---|---|---|
| Original (Week 3, Task 5/6) | 35.7 / 0.1wk / 0.991 / low | 27.6 / 0.1wk / 0.720 / low / **ok** |
| Live app, Week 4–5 (T5.6 → T7 re-verify, repeated) | — / 0.3wk / 0.994 / medium | — / — / — / — / **insufficient_data** |
| Fresh pull #1 (this write-up) | *(429 rate-limited on first attempt)* | 27.9 / 0.1wk / 0.93 / low / **ok** |
| Fresh pull #2, retried (this write-up) | 33.9 / 0.3wk / 0.969 / medium | *(not re-pulled — see below)* |

Three distinct outcomes for the same canonical Austin window (`status: "ok"` with R²=0.720, `status: "ok"` with R²=0.93, and `status: "insufficient_data"`) and two distinct outcomes for Silverstone (half-life 0.1wk vs. 0.3wk) were all observed across these five measurements of the identical fixed window and keyword. **Root cause, confirmed by direct code read (`src/trend_decay_tool.py`):** the `insufficient_data` path fires whenever the extracted decay series has fewer than `MIN_DECAY_SERIES_LENGTH = 3` points, or the 21-day peak window is empty/zero (lines 130–139, 156–157). For a low-search-volume niche keyword like `"Levi's McLaren"`, Google Trends' own relative-interest sampling is noisy enough, pull to pull, that a borderline week's value can land on either side of zero — which is enough to flip the *entire* result between a fitted (if impulse-flagged) estimate and `insufficient_data`, or to shift the fitted half-life between 0.1 and 0.3 weeks depending on exactly which weeks came back non-zero that time.

**This is not a bug in the fixed-window control (Finding 1's fix) — it's a distinct, additional source of unreliability on top of it.** Finding 1 showed that *what window you ask for* changes the answer. Finding 4 shows that *even holding the window fixed*, asking the same question on a different day can change the answer, because Google Trends' relative-interest index for a low-volume keyword is not a stable, reproducible measurement in the first place.

## Why untestable, not falsified

Putting Findings 3 and 4 together: Google Trends weekly data for `"Levi's McLaren"` produces an impulse-like signal around both drops — a spike in the peak week, then a near-immediate floor. Every fit attempted across five separate pulls, whichever exact numbers it returned, has landed in the sub-week half-life range (0.1–0.3 weeks) — never anywhere close to the 3–4 week half-life the report's "6–8 week trend cycle" implies. That consistent shortfall is a genuine, repeated observation, not a one-off artifact.

But two independent limitations mean this cannot be read as *falsifying* the report's claim:

1. **Weekly granularity cannot resolve sub-week decay.** A curve built from two non-zero points spaced weeks apart, dropping from a spike to near-zero, is fit equally well by instantaneous decay as by any other very-fast decay rate — there's no information in the data to distinguish "decayed in 1 day" from "decayed in 4 days," and certainly none to rule out a much slower process that this weekly bucketing is aliasing into an apparent spike. If the underlying social-interest decay genuinely takes 3–4 weeks, but daily/sub-daily fluctuation dominates the weekly-averaged series, weekly resampling could in principle still produce exactly this impulse-then-floor pattern. Nothing in this data rules that out.
2. **The signal itself is not reproducible pull-to-pull** (Finding 4), for a keyword with search volume low enough that Google's own relative-interest normalization is noisy at this scale. A measurement that can't be reliably repeated cannot be used to confidently reject a specific competing claim.

**Falsification would require dense, multi-week decay data — reproducible across repeated pulls — that shows a measured half-life clearly and stably outside the claimed 3–4 week range.** What exists instead is two or three non-zero, mostly-isolated data points per drop, whose exact values shift from pull to pull. That is insufficient resolution to test the claim at all, in either direction — not evidence the claim is wrong.

## Limitations

- **Single data source.** Only Google Trends search-interest data was used; no corroborating signal (social post engagement/impression volume, sell-through/POS velocity, or any other independent trend-interest measure) was in scope for this MVP. The report's claim is about social/commercial trend decay broadly; search-query interest is one proxy for that, and a noisy one at this search volume (see Finding 4) — not a direct measurement.
- **Low search volume for the specific keyword tested.** `"Levi's McLaren"` was the only keyword variant found usable in the Task 4 diagnostic (`"Levi McLaren"`, `"Levi F1"`, `"Levi Formula"` were all SPARSE); even the usable keyword's absolute search volume appears low enough that Google's relative-interest normalization is unstable pull-to-pull (Finding 4).
- **Two data points, not a systematic sample.** Only two drop events (Silverstone, Austin) were analyzed — both from the same 2024 collaboration, both showing the same impulse pattern. This is consistent with (but does not statistically establish) a general claim about how this class of trend decays; a larger sample of comparable drops would strengthen either conclusion.

## Cross-check against the original claim's framing

The BUAN 6390 report frames its trend-cycle claim as "6–8 weeks," which this project has consistently interpreted as implying a **3–4 week half-life** (the point at which interest has decayed to half its peak, roughly the midpoint of a 6–8 week full cycle) — this interpretation is stated explicitly in `src/trend_decay_tool.py`'s own `report_claim` field and has been used consistently since Task 5. Cross-checking this write-up's conclusion against that framing: this document does **not** claim to have shown the report's 6–8 week cycle is wrong, nor does it claim to have confirmed it — both would overclaim relative to what a two-drop, single-source, weekly-granularity, pull-unstable Google Trends analysis can actually support. The conclusion stated here — untestable at this resolution, with a plain-language description of exactly what the data can and cannot say — matches the narrower, honest scope the underlying data supports, consistent with this project's stated purpose (per `README.md`'s "Background" section) of testing the report's claims against primary evidence, not of proving or disproving them outright when the available evidence can't support that strength of conclusion.

## What would resolve this

- **Daily-resolution Google Trends data** (available natively for windows ≤90 days) pulled in the days immediately following each drop, rather than weekly-resampled data, to actually resolve whether the decay happens within days (consistent with this impulse pattern) or is being aliased by the weekly bucketing.
- **Repeated same-window pulls, averaged or interval-estimated**, to characterize (and average out) the pull-to-pull sampling noise documented in Finding 4, rather than treating any single pull's number as authoritative.
- **A higher-volume keyword or a platform with finer relative-volume resolution** — `"Levi's McLaren"` search volume may simply be too low for Google Trends' relative-normalization scheme to expose a smooth decay curve at any granularity, and is demonstrably too low for a stable one.
- **A direct engagement metric** (social post impressions/engagement over time, sell-through velocity) rather than search interest as a proxy, since the report's underlying claim is about social/commercial trend decay, not search-query decay specifically.
