"""EDGAR XBRL companyfacts lookup for Levi's KPI questions.

Standalone module — no FastAPI imports. Called by the router for the
XBRL_KPI dispatch path.
"""

import json
import os
import re

import requests

XBRL_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000094845.json"
CACHE_PATH = "data/xbrl_facts.json"
HEADERS = {"User-Agent": "levis-rag-copilot contact@levisrag.local"}

KPI_MAP = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"],
    "gross profit": ["GrossProfit"],
    "operating income": ["OperatingIncomeLoss"],
    "net income": ["NetIncomeLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "earnings per share": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "inventory": ["InventoryNet"],
}

_QUARTER_TOKENS = ("q1", "q2", "q3", "q4")
_DEFAULT_QUARTER_YEAR = "2025"


def _load_facts() -> dict:
    """Load XBRL companyfacts from the local cache, fetching once if absent."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)

    try:
        response = requests.get(XBRL_URL, headers=HEADERS)
        response.raise_for_status()
        facts = response.json()
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(facts, f)
        return facts
    except Exception as exc:
        print(f"xbrl_tool: failed to fetch XBRL facts — {exc}")
        return {}


def _extract_period(question: str) -> tuple[str | None, str | None]:
    """Parse a fiscal period (fp, fy) from a question, e.g. ("FY", "2025") or ("Q1", "2025")."""
    lowered = question.lower()

    fy_match = re.search(r"fy(20\d\d)", lowered)
    if fy_match:
        return "FY", fy_match.group(1)

    for token in _QUARTER_TOKENS:
        if token in lowered:
            fp = token.upper()
            year_match = re.search(r"(20\d\d)", lowered)
            fy = year_match.group(1) if year_match else _DEFAULT_QUARTER_YEAR
            return fp, fy

    return None, None


def _find_kpi_key(question: str) -> str | None:
    """Return the first KPI_MAP key found in the lowercased question, or None."""
    lowered = question.lower()
    for kpi_key in KPI_MAP:
        if kpi_key in lowered:
            return kpi_key
    return None


def get_kpi(question: str) -> dict:
    """Look up a single XBRL-tagged KPI fact for the period named in the question.

    Args:
        question: Natural-language question, e.g. "What was Levi's gross profit in FY2025?".

    Returns:
        A dict. ``status`` is one of "ok", "no_kpi_match", "no_period_match", "not_found".
    """
    kpi_key = _find_kpi_key(question)
    if kpi_key is None:
        return {"status": "no_kpi_match", "question": question}

    fp, fy = _extract_period(question)
    if fp is None:
        return {"status": "no_period_match", "question": question}

    facts = _load_facts()
    us_gaap = facts.get("facts", {}).get("us-gaap", {})

    for tag in KPI_MAP[kpi_key]:
        tag_data = us_gaap.get(tag)
        if not tag_data:
            continue

        for unit_key, entries in tag_data.get("units", {}).items():
            matches = [
                entry
                for entry in entries
                if entry.get("fp") == fp
                and entry.get("fy") == int(fy)
                and entry.get("form") in ("10-K", "10-Q")
            ]
            if not matches:
                continue

            # EDGAR tags "fy" with the *filing's* fiscal year, not the
            # period each fact covers -- every 10-K re-tags up to 3 years
            # of comparative data under the same fy/fp/form, all sharing
            # one "filed" date. The actual current-period figure is the
            # one with the latest "end" date among the matches.
            best = max(matches, key=lambda entry: entry["end"])
            return {
                "status": "ok",
                "kpi": kpi_key,
                "gaap_tag": tag,
                "value": best["val"],
                "unit": unit_key,
                "period": f"{fp} FY{fy}",
                "form": best["form"],
                "filed": best["filed"],
                "end_date": best["end"],
                "tier": "Verified-from-filing",
                "source": "SEC EDGAR XBRL companyfacts API",
            }

    return {"status": "not_found", "kpi": kpi_key, "period": f"{fp} {fy}"}
