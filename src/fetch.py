"""Fetch Levi's FY2025 10-K filing from SEC EDGAR and extract plain text."""

import logging
from pathlib import Path

import warnings

import requests
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

USER_AGENT = "Sanjay Dilip sanjaydilip7265@gmail.com"
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/94845/000009484526000008/0000094845-26-000008-index.htm"
SEC_BASE_URL = "https://www.sec.gov"

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
EXTRACTED_DIR = Path(__file__).parent.parent / "data" / "extracted"
RAW_HTML_PATH = RAW_DIR / "fy2025_10k.html"
EXTRACTED_TEXT_PATH = EXTRACTED_DIR / "fy2025_10k.txt"


def make_session() -> requests.Session:
    """Create a requests Session with the required EDGAR User-Agent header."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def find_10k_url(session: requests.Session, index_url: str) -> str:
    """Fetch the EDGAR filing index and return the URL of the primary 10-K document.

    Args:
        session: Authenticated requests Session.
        index_url: URL of the EDGAR filing index page.

    Returns:
        Absolute URL of the 10-K HTML document.

    Raises:
        ValueError: If no 10-K document link is found in the index table.
    """
    logger.info("Fetching filing index: %s", index_url)
    response = session.get(index_url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) >= 4 and cells[3].get_text(strip=True) == "10-K":
            link_tag = row.find("a", href=True)
            if link_tag:
                href = link_tag["href"]
                # Strip iXBRL viewer wrapper: /ix?doc=/Archives/...
                if href.startswith("/ix?doc="):
                    href = href[len("/ix?doc="):]
                return href if href.startswith("http") else SEC_BASE_URL + href

    raise ValueError("No 10-K document link found in the filing index.")


def fetch_and_save_html(session: requests.Session, url: str, dest: Path) -> str:
    """Fetch a URL and save the response body as HTML.

    Args:
        session: Authenticated requests Session.
        url: URL to fetch.
        dest: File path to write the raw HTML.

    Returns:
        Raw HTML string.
    """
    logger.info("Fetching 10-K document: %s", url)
    response = session.get(url)
    response.raise_for_status()

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(response.text, encoding="utf-8")
    logger.info("Saved HTML to %s", dest)

    return response.text


def extract_plain_text(html: str, dest: Path) -> str:
    """Strip HTML tags and save plain text.

    Args:
        html: Raw HTML string.
        dest: File path to write the plain text.

    Returns:
        Extracted plain text string.
    """
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n\n", strip=True)

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    logger.info("Saved plain text to %s", dest)

    return text


def main() -> None:
    """Orchestrate fetching, saving, and extracting the 10-K filing."""
    session = make_session()

    doc_url = find_10k_url(session, INDEX_URL)
    html = fetch_and_save_html(session, doc_url, RAW_HTML_PATH)
    text = extract_plain_text(html, EXTRACTED_TEXT_PATH)

    print(f"Total characters: {len(text):,}")
    print("\n--- First 500 characters ---")
    print(text[:500])


if __name__ == "__main__":
    main()
