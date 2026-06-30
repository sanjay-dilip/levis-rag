"""Diagnostic pull of Google Trends data for the McLaren/Levi's drop hypothesis.

Standalone script — no FastAPI imports, no Supabase calls, no curve fitting.
Prints the raw weekly time series per keyword group plus a data-quality
report. Curve fitting / half-life calculation is Task 5 and only proceeds
if this report says USABLE or SPARSE.
"""

import time

import pandas as pd
import requests
from pytrends.exceptions import ResponseError
from pytrends.request import TrendReq

TIMEFRAME = "2024-05-01 2024-12-31"
SILVERSTONE_DATE = pd.Timestamp("2024-07-03")  # British Grand Prix drop
AUSTIN_DATE = pd.Timestamp("2024-10-17")  # U.S. Grand Prix drop

KEYWORD_GROUPS = [
    ["Levi's McLaren"],  # most specific — likely sparse
    ["Levi McLaren"],  # variant without possessive
    ["Levi F1", "Levi Formula"],  # F1-specific, broader
]

# USABLE / SPARSE / EMPTY thresholds (see Step 3 in task spec).
USABLE_MIN_MAX = 20
USABLE_MIN_NONZERO_WEEKS = 8
USABLE_MIN_DROP_VALUE = 10
SPARSE_MIN_MAX = 10

RETRY_SLEEP_SECONDS = 30
BETWEEN_PULL_SLEEP_SECONDS = 2


def _fetch_group(pytrends: TrendReq, kw_list: list[str]) -> pd.DataFrame | None:
    """Pull interest_over_time() for one keyword group, retrying once on rate-limit."""
    try:
        pytrends.build_payload(kw_list, timeframe=TIMEFRAME)
        return pytrends.interest_over_time()
    except (ResponseError, requests.exceptions.TooManyRedirects):
        print(f"Rate limited on {kw_list} — retrying after 30s")
        time.sleep(RETRY_SLEEP_SECONDS)
        try:
            pytrends.build_payload(kw_list, timeframe=TIMEFRAME)
            return pytrends.interest_over_time()
        except (ResponseError, requests.exceptions.TooManyRedirects):
            print(f"Failed: {kw_list}")
            return None


def _nearest(series: pd.Series, target_date: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    """Return the (date, value) pair in series whose index is closest to target_date."""
    diffs = (series.index - target_date).to_series(index=series.index).abs()
    nearest_date = diffs.idxmin()
    return nearest_date, series.loc[nearest_date]


def main() -> None:
    """Pull, print, and grade the Google Trends time series for each keyword group."""
    pytrends = TrendReq(hl="en-US", tz=360)

    # Google Trends auto-selects granularity by window length: ranges over
    # ~269 days return weekly points natively, shorter ranges (this window
    # is ~244 days) return daily points instead. Resample daily -> weekly
    # (mean per ISO week) so the output matches the requested weekly cadence.
    print(
        "NOTE: requested window is ~244 days, below Google Trends' ~269-day "
        "weekly-auto-granularity cutoff. Raw pull is daily; resampling to "
        "weekly (mean per week, W-MON buckets) below.\n"
    )

    results: dict[str, pd.Series] = {}

    for group in KEYWORD_GROUPS:
        print(f"\n=== {group} ===")
        df = _fetch_group(pytrends, group)
        time.sleep(BETWEEN_PULL_SLEEP_SECONDS)

        if df is None or df.empty:
            print("No data returned.")
            continue

        weekly = df.drop(columns=["isPartial"], errors="ignore").resample("W-MON").mean().round(1)

        for kw in group:
            if kw not in weekly.columns:
                print(f"\n--- {kw} ---\nNo column returned for this keyword.")
                continue

            series = weekly[kw]
            print(f"\n--- {kw} ---")
            print("date | interest_value")
            for date, val in series.items():
                print(f"{date.date()} | {val}")

            silverstone_date, silverstone_val = _nearest(series, SILVERSTONE_DATE)
            austin_date, austin_val = _nearest(series, AUSTIN_DATE)
            max_date = series.idxmax()
            max_val = series.max()

            print(f"\nValue nearest Silverstone (2024-07-03): {silverstone_val} (week of {silverstone_date.date()})")
            print(f"Value nearest Austin (2024-10-17): {austin_val} (week of {austin_date.date()})")
            print(f"Max value: {max_val} on {max_date.date()}")

            results[kw] = {
                "series": series,
                "silverstone_val": silverstone_val,
                "austin_val": austin_val,
                "max": max_val,
            }

    print("\n=== DATA QUALITY REPORT ===")
    all_keywords = [kw for group in KEYWORD_GROUPS for kw in group]
    for kw in all_keywords:
        info = results.get(kw)
        if info is None:
            print(f"{kw}: no data returned")
            print("VERDICT: EMPTY")
            continue

        series = info["series"]
        max_val = info["max"]
        non_zero_weeks = int((series > 0).sum())
        total_weeks = len(series)
        silverstone_val = info["silverstone_val"]
        austin_val = info["austin_val"]

        usable = (
            max_val >= USABLE_MIN_MAX
            and non_zero_weeks >= USABLE_MIN_NONZERO_WEEKS
            and (silverstone_val >= USABLE_MIN_DROP_VALUE or austin_val >= USABLE_MIN_DROP_VALUE)
        )
        if usable:
            verdict = "USABLE"
        elif max_val >= SPARSE_MIN_MAX:
            verdict = "SPARSE"
        else:
            verdict = "EMPTY"

        print(
            f"{kw}: max={max_val}, non-zero weeks={non_zero_weeks}/{total_weeks}, "
            f"value@silverstone={silverstone_val}, value@austin={austin_val}"
        )
        print(f"VERDICT: {verdict}")


if __name__ == "__main__":
    main()
