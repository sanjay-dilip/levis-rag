"""Re-embed table chunks with metadata-enriched text to fix poor dense retrieval scores.

Table chunks contain number-dense rows with no semantic context, causing cosine scores
of 0.11–0.20 in Supabase pgvector. Prepending filing metadata gives the embedding model
enough signal to distinguish revenue tables from cost tables, margin tables, etc.
"""

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
ENCODE_BATCH_SIZE = 32
SMOKE_TEST_QUERY = "What was Levi's FY2025 gross margin?"
SMOKE_TEST_TOP_K = 5
SCORE_PASS_THRESHOLD = 0.30


def load_table_chunks(path: Path) -> list[dict]:
    """Load chunks_v2.json and return only the chunks where is_table is True."""
    all_chunks: list[dict] = json.loads(path.read_text(encoding="utf-8"))
    table_chunks = [c for c in all_chunks if c.get("is_table")]
    logger.info(
        "Loaded %d total chunks; %d are table chunks.", len(all_chunks), len(table_chunks)
    )
    return table_chunks


def build_enriched_text(chunk: dict) -> str:
    """Prepend filing metadata to a table chunk's text for richer embedding signal.

    Format: "{filing_type} | {source} | {section} | {original text}"
    The stored text in Supabase is not modified — only the string sent to the encoder.
    """
    return f"{chunk['filing_type']} | {chunk['source']} | {chunk['section']} | {chunk['text']}"


def encode_enriched(texts: list[str], model: SentenceTransformer) -> np.ndarray:
    """Encode *texts* with the given model and return the embedding matrix."""
    logger.info("Encoding %d enriched table texts (batch size %d)...", len(texts), ENCODE_BATCH_SIZE)
    return model.encode(texts, batch_size=ENCODE_BATCH_SIZE, show_progress_bar=True)


def upsert_embeddings(client: Client, chunks: list[dict], embeddings: np.ndarray) -> int:
    """Update only the embedding column for each table chunk in Supabase.

    Uses individual UPDATE ... WHERE id = ? calls rather than upsert so that
    NOT NULL columns (text, source, etc.) are never touched.

    Returns:
        Total number of rows updated.
    """
    total = 0
    for chunk, emb in tqdm(zip(chunks, embeddings), total=len(chunks), desc="Updating embeddings"):
        client.table("chunks").update({"embedding": emb.tolist()}).eq("id", chunk["id"]).execute()
        total += 1

    return total


def run_smoke_test(client: Client, model: SentenceTransformer) -> None:
    """Query match_chunks with the gross margin question and print the top-5 results.

    Pass criterion: at least one is_table=True chunk should appear with similarity > 0.30.
    """
    logger.info('\nSmoke test: "%s"', SMOKE_TEST_QUERY)
    query_vec = model.encode(SMOKE_TEST_QUERY).tolist()

    response = client.rpc(
        "match_chunks",
        {"query_embedding": query_vec, "match_count": SMOKE_TEST_TOP_K},
    ).execute()

    results: list[dict] = response.data
    if not results:
        print("  Smoke test returned no results — check RPC function.")
        return

    print(f"\n  Top {SMOKE_TEST_TOP_K} dense results for: \"{SMOKE_TEST_QUERY}\"\n")
    passed = False
    for rank, row in enumerate(results, start=1):
        similarity = row.get("similarity", float("nan"))
        is_table = row.get("is_table", False)
        tag = "[TABLE]" if is_table else "      "
        print(
            f"  [{rank}] {tag} id={row['id']:4d}  sim={similarity:.4f}  "
            f"{row.get('filing_type', '?'):5s} | {row.get('section', '')[:50]}"
        )
        if is_table and similarity > SCORE_PASS_THRESHOLD:
            passed = True

    print()
    if passed:
        print(f"  PASS — at least one table chunk scored above {SCORE_PASS_THRESHOLD}.")
    else:
        print(
            f"  WARN — no table chunk scored above {SCORE_PASS_THRESHOLD}. "
            "Enrichment may need further tuning."
        )


def main() -> None:
    """Enrich and re-upload embeddings for all table chunks, then smoke-test retrieval."""
    load_dotenv()

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    client = create_client(url, key)
    logger.info("Supabase client initialised (service role).")

    table_chunks = load_table_chunks(CHUNKS_PATH)

    logger.info("Loading model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    enriched_texts = [build_enriched_text(c) for c in table_chunks]
    embeddings = encode_enriched(enriched_texts, model)

    logger.info("Updating embeddings in Supabase (one UPDATE per row)...")
    total_upserted = upsert_embeddings(client, table_chunks, embeddings)

    print(f"\nSummary:")
    print(f"  Table chunks re-embedded : {len(table_chunks)}")
    print(f"  Rows updated in Supabase : {total_upserted}")

    run_smoke_test(client, model)


if __name__ == "__main__":
    main()
