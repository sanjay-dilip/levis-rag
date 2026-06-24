"""Fetch and extract recent Levi Strauss SEC filings (10-K, 10-Q, 8-K) from EDGAR."""

import logging
import time
import warnings
from pathlib import Path

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

USER_AGENT = "Sanjay Dilip sanjaydilip7265@gmail.com"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0000094845.json"
SEC_BASE_URL = "https://www.sec.gov"
CIK = "94845"

ALLOWED_FORMS = {"10-K", "10-Q", "8-K"}
CUTOFF_DATE = "2024-01-01"

RAW_DIR = Path("data/raw")
EXTRACTED_DIR = Path("data/extracted")


def make_session() -> requests.Session:
    """Create a requests Session with the required EDGAR User-Agent header."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def fetch_filings_metadata(session: requests.Session) -> list[dict]:
    """Fetch the EDGAR submissions JSON and return filtered filing records.

    Returns:
        List of dicts with keys: accession_number, form, filing_date, primary_document.
    """
    logger.info("Fetching submissions metadata: %s", SUBMISSIONS_URL)
    response = session.get(SUBMISSIONS_URL)
    response.raise_for_status()

    recent = response.json()["filings"]["recent"]
    accession_numbers = recent["accessionNumber"]
    forms = recent["form"]
    filing_dates = recent["filingDate"]
    primary_docs = recent["primaryDocument"]

    filings = []
    for acc, form, date, doc in zip(accession_numbers, forms, filing_dates, primary_docs):
        if form in ALLOWED_FORMS and date >= CUTOFF_DATE:
            filings.append(
                {
                    "accession_number": acc,
                    "form": form,
                    "filing_date": date,
                    "primary_document": doc,
                }
            )

    return filings


def print_summary(filings: list[dict]) -> None:
    """Print a formatted summary table of the filtered filings."""
    print(f"\n{'Form':<8} {'Filing Date':<14} {'Accession Number'}")
    print("-" * 50)
    for f in filings:
        print(f"{f['form']:<8} {f['filing_date']:<14} {f['accession_number']}")
    print(f"\nTotal: {len(filings)} filings\n")


def find_document_url(session: requests.Session, accession_number: str, form: str) -> str:
    """Fetch the EDGAR filing index and return the URL of the primary document.

    Args:
        session: Authenticated requests Session.
        accession_number: Accession number with dashes (e.g. 0000094845-26-000008).
        form: Form type string to match in the index table (e.g. '10-K').

    Returns:
        Absolute URL of the primary filing document.

    Raises:
        ValueError: If no matching document link is found in the index.
    """
    acc_no_dashes = accession_number.replace("-", "")
    index_url = (
        f"{SEC_BASE_URL}/Archives/edgar/data/{CIK}"
        f"/{acc_no_dashes}/{accession_number}-index.htm"
    )
    logger.info("Fetching index: %s", index_url)
    response = session.get(index_url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 4 and cells[3].get_text(strip=True) == form:
            link_tag = row.find("a", href=True)
            if link_tag:
                href = link_tag["href"]
                if href.startswith("/ix?doc="):
                    href = href[len("/ix?doc="):]
                return href if href.startswith("http") else SEC_BASE_URL + href

    raise ValueError(f"No {form} document link found in index: {index_url}")


def fetch_and_save(session: requests.Session, filing: dict) -> None:
    """Fetch, extract, and save one filing's HTML and plain text.

    Args:
        session: Authenticated requests Session.
        filing: Dict with accession_number, form, filing_date, primary_document.
    """
    form = filing["form"]
    date = filing["filing_date"]
    acc = filing["accession_number"]
    stem = f"{form}_{date}_{acc}"

    doc_url = find_document_url(session, acc, form)

    logger.info("Fetching document: %s", doc_url)
    response = session.get(doc_url)
    response.raise_for_status()
    html = response.text

    raw_path = RAW_DIR / f"{stem}.html"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(html, encoding="utf-8")
    print(f"  Saved HTML : {raw_path}")

    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)

    extracted_path = EXTRACTED_DIR / f"{stem}.txt"
    extracted_path.parent.mkdir(parents=True, exist_ok=True)
    extracted_path.write_text(text, encoding="utf-8")
    print(f"  Saved text : {extracted_path}")


def main() -> None:
    """Orchestrate metadata fetch, summary print, and per-filing download."""
    session = make_session()

    filings = fetch_filings_metadata(session)
    print_summary(filings)

    for i, filing in enumerate(filings):
        print(f"[{i + 1}/{len(filings)}] {filing['form']} — {filing['filing_date']} — {filing['accession_number']}")
        try:
            fetch_and_save(session, filing)
        except Exception as exc:
            logger.error("Failed to process %s: %s", filing["accession_number"], exc)

        if i < len(filings) - 1:
            time.sleep(1)


if __name__ == "__main__":
    main()
