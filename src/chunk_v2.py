"""Section-aware, table-safe chunker for all ingested SEC filings.

Replaces src/chunk.py (Day 3). The numpy flat-file approach (data/embeddings.npy)
is fully retired — embeddings now live in Supabase (pgvector).
"""

import json
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

EXTRACTED_DIR = Path("data/extracted")
OUTPUT_PATH = Path("data/chunks_v2.json")
TARGET_WORDS = 600
MIN_TABLE_ROWS = 3

SECTION_PATTERNS = [
    r"(?i)^item\s+\d+[a-z]?\.",
    r"(?i)^management.s discussion",
    r"(?i)^risk factors",
    r"(?i)^financial statements",
    r"(?i)^notes to consolidated",
    r"(?i)^quantitative and qualitative",
    r"(?i)^controls and procedures",
    r"(?i)^legal proceedings",
    r"(?i)^unregistered sales",
]

KNOWN_TYPES = {"10-K", "10-Q", "8-K"}


def is_table_line(line: str) -> bool:
    """Return True if *line* contains 3 or more numbers separated by whitespace."""
    return len(re.findall(r"[\d,]+\.?\d*", line)) >= 3


def detect_section(line: str) -> str | None:
    """Return the stripped line text if it matches a section header pattern, else None."""
    stripped = line.strip()
    for pattern in SECTION_PATTERNS:
        if re.match(pattern, stripped):
            return stripped
    return None


def chunk_document(text: str, source_filename: str, filing_type: str) -> list[dict]:
    """Split *text* into section-aware, table-safe chunks.

    Args:
        text: Plain text content of one filing.
        source_filename: Base filename used as the source field.
        filing_type: One of '10-K', '10-Q', '8-K'.

    Returns:
        List of chunk dicts (id field is placeholder -1; caller assigns final IDs).
    """
    lines = text.split("\n")
    chunks: list[dict] = []
    current_section = "preamble"
    buffer: list[str] = []

    def emit(buf: list[str], section: str, is_table: bool = False) -> None:
        joined = "\n".join(buf).strip()
        if joined:
            chunks.append(
                {
                    "id": -1,
                    "text": joined,
                    "source": source_filename,
                    "filing_type": filing_type,
                    "section": section,
                    "word_count": len(joined.split()),
                    "is_table": is_table,
                }
            )

    i = 0
    while i < len(lines):
        line = lines[i]

        # Section header → flush buffer, start new section
        section = detect_section(line)
        if section is not None:
            emit(buffer, current_section)
            buffer = [line]
            current_section = section
            i += 1
            continue

        # Table block detection: scan ahead for 3+ consecutive table lines
        if is_table_line(line):
            j = i
            while j < len(lines) and is_table_line(lines[j]):
                j += 1
            if j - i >= MIN_TABLE_ROWS:
                emit(buffer, current_section)
                buffer = []
                emit(lines[i:j], current_section, is_table=True)
                i = j
                continue

        buffer.append(line)

        # Flush when buffer hits the word target
        if len(" ".join(buffer).split()) >= TARGET_WORDS:
            emit(buffer, current_section)
            buffer = []

        i += 1

    emit(buffer, current_section)
    return chunks


def infer_filing_type(filename: str) -> str | None:
    """Return the filing type prefix from a filename, or None if not recognised."""
    for ft in KNOWN_TYPES:
        if filename.startswith(ft):
            return ft
    return None


def main() -> None:
    """Chunk all extracted .txt files and save to chunks_v2.json."""
    txt_files = sorted(EXTRACTED_DIR.glob("*.txt"))
    all_chunks: list[dict] = []
    skipped: list[str] = []

    for filepath in txt_files:
        filing_type = infer_filing_type(filepath.name)
        if filing_type is None:
            skipped.append(filepath.name)
            continue

        text = filepath.read_text(encoding="utf-8")
        chunks = chunk_document(text, filepath.name, filing_type)
        all_chunks.extend(chunks)
        logger.info("%s → %d chunks", filepath.name, len(chunks))

    if skipped:
        logger.info("Skipped (no recognised prefix): %s", ", ".join(skipped))

    for idx, chunk in enumerate(all_chunks):
        chunk["id"] = idx

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(all_chunks, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Saved %d chunks to %s", len(all_chunks), OUTPUT_PATH)

    total = len(all_chunks)
    table_count = sum(1 for c in all_chunks if c["is_table"])
    avg_words = sum(c["word_count"] for c in all_chunks) / total if total else 0

    by_type: dict[str, int] = {}
    for c in all_chunks:
        by_type[c["filing_type"]] = by_type.get(c["filing_type"], 0) + 1

    # Last run: 1449 total chunks, 318.2 avg word count
    print(f"\nTotal chunks   : {total}")
    print(f"Table chunks   : {table_count}")
    print(f"Avg word count : {avg_words:.1f}")
    print("By filing type :")
    for ft in sorted(by_type):
        print(f"  {ft}: {by_type[ft]}")


if __name__ == "__main__":
    main()
