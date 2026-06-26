"""
Backfill fiscal_year and period_of_report columns in the Supabase chunks table.

Requires the two columns to exist already (run ALTER TABLE in Supabase SQL editor
before executing this script):

    ALTER TABLE chunks ADD COLUMN IF NOT EXISTS fiscal_year text;
    ALTER TABLE chunks ADD COLUMN IF NOT EXISTS period_of_report text;

NOTE on the filing-date quarter rule in the task spec:
The spec says "Filed Apr–Jun → Q2", but Levi's actual filings show April filings
are Q1 (period ended February/March). Quarter labels are derived here from the
actual period-of-report dates extracted from each file, not from the filing date.
"""

import logging
import os
from collections import defaultdict

from dotenv import load_dotenv
from supabase import create_client, Client
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded mapping: filename pattern → fiscal metadata
# Period dates confirmed from "For the Quarterly Period Ended" in each file.
# ---------------------------------------------------------------------------

FILING_METADATA: dict[str, dict[str, str]] = {
    # Annual 10-K filings
    "10-K_2026-01-28": {"fiscal_year": "FY2025", "period_of_report": "2025-11-30"},
    "10-K_2025-01-29": {"fiscal_year": "FY2024", "period_of_report": "2024-12-01"},
    "10-K_2024-01-25": {"fiscal_year": "FY2023", "period_of_report": "2023-11-26"},
    # Original single-file FY2025 10-K extraction (fetch.py, Day 1)
    "fy2025_10k":      {"fiscal_year": "FY2025", "period_of_report": "2025-11-30"},
    # Quarterly 10-Q filings — period dates read directly from filing text
    "10-Q_2026-04-07": {"fiscal_year": "FY2026", "period_of_report": "2026-03-01"},
    "10-Q_2025-10-09": {"fiscal_year": "FY2025", "period_of_report": "2025-08-31"},
    "10-Q_2025-07-10": {"fiscal_year": "FY2025", "period_of_report": "2025-06-01"},
    "10-Q_2025-04-07": {"fiscal_year": "FY2025", "period_of_report": "2025-03-02"},
    "10-Q_2024-10-02": {"fiscal_year": "FY2024", "period_of_report": "2024-08-25"},
    "10-Q_2024-06-26": {"fiscal_year": "FY2024", "period_of_report": "2024-05-26"},
    "10-Q_2024-04-03": {"fiscal_year": "FY2024", "period_of_report": "2024-02-25"},
    # 8-K filings: event-driven, not mapped to a fiscal period
    # fiscal_year and period_of_report left NULL (default for new column)
}


def build_client() -> Client:
    """Return an authenticated Supabase client using the service key."""
    load_dotenv()
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def print_distinct_10q_sources(supabase: Client) -> None:
    """Query and print all distinct 10-Q source values from the chunks table."""
    logger.info("\n--- Distinct 10-Q source values in chunks table ---")
    response = (
        supabase.table("chunks")
        .select("source")
        .eq("filing_type", "10-Q")
        .execute()
    )
    sources = sorted({row["source"] for row in response.data})
    for s in sources:
        logger.info("  %s", s)
    logger.info("")


def run_updates(supabase: Client) -> None:
    """Update fiscal_year and period_of_report for each mapped filing pattern."""
    for pattern, meta in tqdm(FILING_METADATA.items(), desc="Updating filings"):
        fiscal_year = meta["fiscal_year"]
        period_of_report = meta["period_of_report"]
        response = (
            supabase.table("chunks")
            .update({"fiscal_year": fiscal_year, "period_of_report": period_of_report})
            .like("source", f"%{pattern}%")
            .execute()
        )
        count = len(response.data) if response.data else 0
        logger.info(
            "  %-30s → fiscal_year=%-7s  period=%s  rows_updated=%d",
            pattern, fiscal_year, period_of_report, count,
        )


def print_verification(supabase: Client) -> None:
    """
    Fetch all chunks and group by filing_type / source / fiscal_year /
    period_of_report, then print the verification table.
    """
    logger.info("\n--- Verification: chunks grouped by filing metadata ---\n")
    response = (
        supabase.table("chunks")
        .select("filing_type, source, fiscal_year, period_of_report")
        .execute()
    )

    # Group and count in Python (PostgREST does not support GROUP BY)
    counts: dict[tuple, int] = defaultdict(int)
    for row in response.data:
        key = (
            row["filing_type"],
            row["source"],
            row["fiscal_year"],
            row["period_of_report"],
        )
        counts[key] += 1

    header = f"{'filing_type':<10}  {'source':<50}  {'fiscal_year':<11}  {'period_of_report':<18}  {'chunk_count':>11}"
    logger.info(header)
    logger.info("-" * len(header))

    for key in sorted(counts.keys(), key=lambda k: (k[0], k[3] or "", k[1])):
        filing_type, source, fiscal_year, period_of_report = key
        logger.info(
            "%-10s  %-50s  %-11s  %-18s  %11d",
            filing_type,
            source,
            fiscal_year or "NULL",
            period_of_report or "NULL",
            counts[key],
        )

    # Spot-check assertions
    logger.info("\n--- Spot-check assertions ---")
    rows = response.data
    fy2024_10k = [r for r in rows if "10-K_2025-01-29" in r["source"]]
    fy2025_10k = [r for r in rows if "10-K_2026-01-28" in r["source"]]
    null_10k = [
        r for r in rows
        if r["filing_type"] == "10-K" and r["fiscal_year"] is None
    ]
    nonnull_8k = [
        r for r in rows
        if r["filing_type"] == "8-K" and r["fiscal_year"] is not None
    ]

    logger.info(
        "10-K_2025-01-29 fiscal_year = FY2024:  %s (%d rows checked)",
        all(r["fiscal_year"] == "FY2024" for r in fy2024_10k),
        len(fy2024_10k),
    )
    logger.info(
        "10-K_2026-01-28 fiscal_year = FY2025:  %s (%d rows checked)",
        all(r["fiscal_year"] == "FY2025" for r in fy2025_10k),
        len(fy2025_10k),
    )
    logger.info(
        "No 10-K rows with NULL fiscal_year:     %s (%d unexpected NULLs)",
        len(null_10k) == 0,
        len(null_10k),
    )
    logger.info(
        "8-K rows have NULL fiscal_year:         %s (%d unexpected non-NULLs)",
        len(nonnull_8k) == 0,
        len(nonnull_8k),
    )


def main() -> None:
    """Entry point."""
    supabase = build_client()
    print_distinct_10q_sources(supabase)
    run_updates(supabase)
    print_verification(supabase)


if __name__ == "__main__":
    main()
