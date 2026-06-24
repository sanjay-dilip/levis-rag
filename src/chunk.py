"""Chunk the extracted 10-K plain text into overlapping word-count-targeted segments."""

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

INPUT_PATH = Path("data/extracted/fy2025_10k.txt")
OUTPUT_PATH = Path("data/chunks.json")
SOURCE_NAME = "fy2025_10k"
TARGET_WORDS = 600
OVERLAP_WORDS = 50


def load_paragraphs(path: Path) -> list[str]:
    """Split raw text on double newlines and return non-empty paragraph strings."""
    raw = path.read_text(encoding="utf-8")
    return [p.strip() for p in raw.split("\n\n") if p.strip()]


def word_count(text: str) -> int:
    """Return the number of whitespace-delimited tokens in *text*."""
    return len(text.split())


def build_chunks(paragraphs: list[str]) -> list[dict]:
    """
    Group paragraphs into chunks targeting TARGET_WORDS words each.

    Overlap is implemented by keeping the last paragraph of the previous
    chunk as the first paragraph of the next chunk (50-word proximity).
    """
    chunks: list[dict] = []
    i = 0
    overlap_para: str | None = None

    while i < len(paragraphs):
        group: list[str] = []
        total = 0

        if overlap_para is not None:
            group.append(overlap_para)
            total += word_count(overlap_para)

        while i < len(paragraphs) and total < TARGET_WORDS:
            para = paragraphs[i]
            group.append(para)
            total += word_count(para)
            i += 1

        if not group:
            break

        text = "\n\n".join(group)
        overlap_para = group[-1] if word_count(group[-1]) <= OVERLAP_WORDS * 2 else None

        chunks.append(
            {
                "id": len(chunks),
                "text": text,
                "source": SOURCE_NAME,
                "word_count": word_count(text),
            }
        )

    return chunks


def main() -> None:
    """Load, chunk, save, and summarise the 10-K text."""
    paragraphs = load_paragraphs(INPUT_PATH)
    logger.info("Loaded %d paragraphs from %s", len(paragraphs), INPUT_PATH)

    chunks = build_chunks(paragraphs)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(chunks, indent=2, ensure_ascii=False), encoding="utf-8")

    avg_words = sum(c["word_count"] for c in chunks) / len(chunks) if chunks else 0
    print(f"Total chunks     : {len(chunks)}")
    print(f"Avg words/chunk  : {avg_words:.1f}")
    print(f"Chunk 0 preview  : {chunks[0]['text'][:200]!r}")


if __name__ == "__main__":
    main()
