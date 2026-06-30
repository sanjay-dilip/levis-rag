"""Exponential decay curve fitting for Google Trends search interest.

Standalone module — no FastAPI imports. Called by the router in Task 6.
Builds on the findings from trend_diagnostic.py (Task 4): only
"Levi's McLaren" around the Silverstone drop had a usable signal: max=35.7,
8/36 non-zero weeks. The Austin drop (max signal 2.3) is expected to hit
the insufficient_data path.
"""

import math

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from pytrends.request import TrendReq

PEAK_WINDOW_DAYS = 21
ZERO_RUN_LENGTH = 3
MIN_DECAY_SERIES_LENGTH = 3

HIGH_CONFIDENCE_MIN_LENGTH = 6
HIGH_CONFIDENCE_MIN_R2 = 0.80
MEDIUM_CONFIDENCE_MIN_LENGTH = 3
MEDIUM_CONFIDENCE_MIN_R2 = 0.60

REPORT_CLAIM_MIN_WEEKS = 3.0
REPORT_CLAIM_MAX_WEEKS = 4.0
REPORT_CLAIM_TEXT = "6–8 week trend cycle (half-life interpreted as 3–4 weeks)"

METHODOLOGY_NOTE = (
    "Raw Google Trends data was returned at daily granularity for this "
    "window and resampled to weekly (ISO week mean) before fitting. "
    "Interest values are relative (0–100), normalised to the peak within "
    "the requested window."
)


def _empty_result(keyword: str, drop_date: str, status: str, **extra: object) -> dict:
    """Build a return dict with all optional fields defaulted to None."""
    result = {
        "keyword": keyword,
        "drop_date": drop_date,
        "status": status,
        "peak_date": None,
        "peak_value": None,
        "half_life_weeks": None,
        "half_life_days": None,
        "r_squared": None,
        "confidence": None,
        "decay_series_length": None,
        "vs_report_claim": None,
        "methodology_note": METHODOLOGY_NOTE,
        "report_claim": REPORT_CLAIM_TEXT,
    }
    result.update(extra)
    return result


def _pull_weekly_series(keyword: str, window_start: str, window_end: str) -> pd.Series:
    """Pull Google Trends interest for one keyword and resample daily->weekly."""
    pytrends = TrendReq(hl="en-US", tz=360)
    pytrends.build_payload([keyword], timeframe=f"{window_start} {window_end}")
    df = pytrends.interest_over_time()

    if df.empty:
        return pd.Series(dtype=float)

    weekly = df.drop(columns=["isPartial"], errors="ignore").resample("W-MON").mean().round(1)
    return weekly[keyword]


def _decay_func(t: np.ndarray, a: float, lambda_: float) -> np.ndarray:
    """Exponential decay model: f(t) = A * exp(-lambda * t)."""
    return a * np.exp(-lambda_ * t)


def compute_half_life(
    keyword: str,
    drop_date: str,
    window_start: str,
    window_end: str,
) -> dict:
    """Fit an exponential decay curve to post-drop search interest and return a half-life.

    Args:
        keyword: Google Trends search term.
        drop_date: ISO date of the trend-triggering event, e.g. "2024-07-03".
        window_start: ISO date for the start of the pytrends pull window.
        window_end: ISO date for the end of the pytrends pull window.

    Returns:
        A dict conforming to the fixed return schema (see module docstring).
        ``status`` is one of "ok", "insufficient_data", "fit_failed", "error".
    """
    try:
        series = _pull_weekly_series(keyword, window_start, window_end)
    except Exception as exc:  # pytrends/network failures
        return _empty_result(keyword, drop_date, "error", error_message=str(exc))

    if series.empty:
        return _empty_result(keyword, drop_date, "insufficient_data")

    # Step 2 — locate the peak within [drop_date, drop_date + 21 days].
    drop_ts = pd.Timestamp(drop_date)
    peak_window_end = drop_ts + pd.Timedelta(days=PEAK_WINDOW_DAYS)
    peak_window = series[(series.index >= drop_ts) & (series.index <= peak_window_end)]

    if peak_window.empty or peak_window.max() <= 0:
        return _empty_result(keyword, drop_date, "insufficient_data")

    peak_date = peak_window.idxmax()
    peak_value = float(peak_window.loc[peak_date])

    # Step 3 — extract the decay series: peak onwards, until 3 consecutive
    # zero weeks (trimmed back to the first zero), or the end of the series.
    post_peak = series.loc[peak_date:]
    decay_values: list[float] = []
    zero_run = 0
    for value in post_peak:
        decay_values.append(float(value))
        zero_run = zero_run + 1 if value == 0 else 0
        if zero_run >= ZERO_RUN_LENGTH:
            decay_values = decay_values[: len(decay_values) - (ZERO_RUN_LENGTH - 1)]
            break

    if len(decay_values) < MIN_DECAY_SERIES_LENGTH:
        return _empty_result(keyword, drop_date, "insufficient_data")

    # Step 4 — fit f(t) = A * exp(-lambda * t), t = weeks since peak.
    t = np.arange(len(decay_values), dtype=float)
    y = np.array(decay_values, dtype=float)

    try:
        popt, _ = curve_fit(
            _decay_func, t, y, p0=[decay_values[0], 0.1], bounds=([0, 0], [100, 10])
        )
    except RuntimeError:
        return _empty_result(keyword, drop_date, "fit_failed")

    a_fit, lambda_fit = popt

    if lambda_fit <= 0:
        return _empty_result(keyword, drop_date, "fit_failed")

    half_life_weeks = round(float(math.log(2) / lambda_fit), 1)
    half_life_days = round(half_life_weeks * 7)

    y_pred = _decay_func(t, a_fit, lambda_fit)
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = round(1.0 if ss_res == 0 else 0.0, 3) if ss_tot == 0 else round(1 - ss_res / ss_tot, 3)

    # Step 5 — confidence.
    if len(decay_values) >= HIGH_CONFIDENCE_MIN_LENGTH and r_squared >= HIGH_CONFIDENCE_MIN_R2:
        confidence = "high"
    elif len(decay_values) >= MEDIUM_CONFIDENCE_MIN_LENGTH and r_squared >= MEDIUM_CONFIDENCE_MIN_R2:
        confidence = "medium"
    else:
        confidence = "low"

    # Step 6 — compare to report claim.
    if REPORT_CLAIM_MIN_WEEKS <= half_life_weeks <= REPORT_CLAIM_MAX_WEEKS:
        vs_report_claim = "within_range"
    elif half_life_weeks < REPORT_CLAIM_MIN_WEEKS:
        vs_report_claim = "shorter"
    else:
        vs_report_claim = "longer"

    return _empty_result(
        keyword,
        drop_date,
        "ok",
        peak_date=peak_date.date().isoformat(),
        peak_value=peak_value,
        half_life_weeks=half_life_weeks,
        half_life_days=half_life_days,
        r_squared=r_squared,
        confidence=confidence,
        decay_series_length=len(decay_values),
        vs_report_claim=vs_report_claim,
    )
