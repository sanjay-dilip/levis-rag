"""Embed all chunks from chunks_v2.json and upsert them into Supabase."""

import json
import logging
import os
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = Path("data/chunks_v2.json")
MODEL_NAME = "all-MiniLM-L6-v2"
ENCODE_BATCH_SIZE = 64
INSERT_BATCH_SIZE = 100


def load_supabase_client() -> Client:
    """Initialise and return a Supabase client using the service role key.

    Uses SUPABASE_SERVICE_KEY (bypasses RLS) for backend write operations.
    """
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def encode_chunks(texts: list[str]) -> np.ndarray:
    """Encode *texts* in batches and return the embedding matrix."""
    logger.info("Loading model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)
    logger.info("Encoding %d texts (batch size %d)...", len(texts), ENCODE_BATCH_SIZE)
    embeddings = model.encode(
        texts,
        batch_size=ENCODE_BATCH_SIZE,
        show_progress_bar=True,
    )
    return embeddings


def build_row(chunk: dict, embedding: np.ndarray) -> dict:
    """Merge a chunk dict with its embedding, converting the vector to a plain list."""
    return {
        "id": chunk["id"],
        "text": chunk["text"],
        "source": chunk["source"],
        "filing_type": chunk["filing_type"],
        "section": chunk["section"],
        "word_count": chunk["word_count"],
        "is_table": chunk["is_table"],
        "embedding": embedding.tolist(),
    }


def insert_batches(client: Client, rows: list[dict]) -> int:
    """Insert *rows* into the chunks table in batches of INSERT_BATCH_SIZE.

    Returns:
        Total number of rows inserted.
    """
    total = 0
    for start in range(0, len(rows), INSERT_BATCH_SIZE):
        batch = rows[start : start + INSERT_BATCH_SIZE]
        client.table("chunks").upsert(batch).execute()
        total += len(batch)
        print(f"  Inserted rows {start + 1}–{total} of {len(rows)}")
    return total


def main() -> None:
    """Load chunks, embed, and push to Supabase."""
    load_dotenv()

    client = load_supabase_client()
    logger.info("Supabase client initialised")

    chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    logger.info("Loaded %d chunks from %s", len(chunks), CHUNKS_PATH)

    texts = [c["text"] for c in chunks]
    embeddings = encode_chunks(texts)

    rows = [build_row(chunk, emb) for chunk, emb in zip(chunks, embeddings)]

    logger.info("Inserting %d rows into Supabase (batch size %d)...", len(rows), INSERT_BATCH_SIZE)
    total_inserted = insert_batches(client, rows)

    print(f"\nDone. Total rows inserted: {total_inserted}")


if __name__ == "__main__":
    main()
