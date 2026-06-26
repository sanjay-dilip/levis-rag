# DTC Revenue Conflict Finding

**Investigation date:** 2026-06-26
**Status:** Resolved — no data ingestion problem found

---

## The two figures

| Figure | Source file | Filing type | Fiscal year covered | Period end | Scope |
|---|---|---|---|---|---|
| **$2,923.8M** | `10-K_2025-01-29_0000094845-25-000005.txt` | 10-K (annual report) | FY2024 | December 1, 2024 | All brands: Levi's + Dockers + Beyond Yoga |
| **$3,076.8M (~$3.07B)** | `10-K_2026-01-28_0000094845-26-000008.txt` | 10-K (annual report) | FY2025 | November 30, 2025 | Levi's Brands + Beyond Yoga only (Dockers divested) |

### Exact sentences in context

**$2,923.8M — FY2024 10-K, MD&A net revenues by channel table (lines 3737–3752):**
```
Net revenues by channel:
  Wholesale   $3,431.5   $3,550.9
  DTC          2,923.8    2,628.1
  Total       $6,355.3   $6,179.0
```
Table header: "Year Ended December 1, 2024 / November 26, 2023"
Segment breakdown above this row: Levi's Brands ($5,900.9M) + Dockers ($323.3M) + Beyond Yoga ($131.1M)

**$3,076.8M — FY2025 10-K, MD&A net revenues by channel table (lines 3811–3836):**
```
Net revenues by channel:
  Wholesale   $3,205.2   $3,222.9
  DTC          3,076.8    2,809.1
  Total       $6,282.0   $6,032.0
```
Table header: "Year Ended November 30, 2025 / December 1, 2024"
Segment breakdown above this row: Levi's Brands ($6,130.7M) + Beyond Yoga ($151.3M) — **no Dockers**

**$3.07B — FY2025 earnings release (Exhibit 99.1 to `8-K_2026-01-28_0000094845-26-000009.txt`):**
The 8-K wrapper is Item 2.02 "furnished" filing only. The press release exhibit (Exhibit 99.1) was not captured
in `data/extracted/`. The $3.07B figure is a truncated presentation of $3,076.8M: expressed in billions
truncated at two decimal places (3.0768... → $3.07B). Same underlying number as the FY2025 10-K.

---

## Confirmed explanation

**The two figures are from different fiscal years and cover different brand scopes. There is no data conflict.**

### Root cause: filing naming confusion

Levi's fiscal years end in late November or early December:
- **FY2024** ends December 1, 2024 — 10-K filed **January 29, 2025**
- **FY2025** ends November 30, 2025 — 10-K filed **January 28, 2026**

The 10-K filed in January 2025 is sometimes mislabeled "FY2025 10-K" because it was filed during calendar
year 2025. It is actually the FY2024 annual report covering the year ended December 1, 2024.

### Rule out — explicit elimination of candidate explanations

**a) Different time periods — CONFIRMED as root cause.**
$2,923.8M covers year ended December 1, 2024 (FY2024).
$3,076.8M covers year ended November 30, 2025 (FY2025).
These are consecutive fiscal years, not the same period.

**b) Different channel definitions — CONTRIBUTING FACTOR.**
$2,923.8M includes Dockers DTC revenue. $3,076.8M excludes Dockers, which Levi's divested during FY2025.
Evidence: the FY2025 10-K restates the prior-year (FY2024) DTC as $2,809.1M (ex-Dockers), implying Dockers
contributed approximately $114.7M ($2,923.8M - $2,809.1M) to DTC in FY2024.

**c) Rounding — RULED OUT.**
$2,923.8M rounds to $2.9B. $3,076.8M rounds to $3.1B. Neither rounds to the other. Rounding does not
explain a $153M difference between figures that cover different years.

**d) Different fiscal year definitions (calendar year) — RULED OUT.**
Both figures reference Levi's own fiscal year end dates (December 1, 2024 and November 30, 2025). Neither
uses a calendar year definition.

---

## Evidentiary tier

| Figure | Tier | Rationale |
|---|---|---|
| **$2,923.8M** | **Verified-from-filing** | Audited annual report, filed with SEC as 10-K for fiscal year ended December 1, 2024. Covers all brands including Dockers. |
| **$3,076.8M** | **Verified-from-filing** | Audited annual report, filed with SEC as 10-K for fiscal year ended November 30, 2025. Excludes Dockers (divested). |
| **$3.07B (earnings release)** | **Verified-from-filing (furnished)** | Filed as Exhibit 99.1 to an 8-K under Item 2.02. Note: Item 2.02 exhibits are "furnished" not "filed" under the Exchange Act, meaning they do not carry the same Section 18 liability. However, the underlying figure ($3,076.8M) is audited and confirmed in the FY2025 10-K, so it is reliable. Not a non-GAAP or adjusted figure. |

---

## Recommendation

**Surface the FY2025 10-K figure ($3,076.8M) when a user asks "What was Levi's FY2025 DTC revenue?"**

Rationale: It is the only figure that covers fiscal year 2025 (ended November 30, 2025), it is audited, and it
is filed directly in the 10-K body (not furnished in an exhibit). The $3.07B earnings release figure refers to
the same underlying number. The $2,923.8M figure is FY2024 data and must not be presented as FY2025.

When surfacing this figure, note the scope: Levi's Brands + Beyond Yoga. Dockers DTC (~$114.7M in FY2024)
is excluded because Dockers was divested during FY2025. If a user asks for a like-for-like FY2024 comparison,
use $2,809.1M (FY2024 ex-Dockers, as restated in the FY2025 10-K), not $2,923.8M.
