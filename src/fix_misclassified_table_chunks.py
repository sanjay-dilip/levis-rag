"""Re-embed specific chunks whose dense embedding is diluted by mixed-topic
content, using a hand-written, content-accurate descriptive sentence prefix
instead of the generic metadata prefix used in enrich_table_embeddings.py.

Chunk 602 mixes an income-statement continuation (operating income through
EPS) with a separate net-revenues-by-segment table and narrative -- its plain
embedding and the generic "{filing_type} | {source} | {section}" prefix both
underperform (cosine ~0.39 and ~0.38 against "What was Levi's FY2025 net
income?") because the pooled embedding is dominated by the much larger
revenue-segment content. A specific, accurate sentence naming the answer
directly raises this to cosine ~0.61 (verified locally before writing to
Supabase -- see session notes). Explicit id->prefix map, not a generic
batch job -- narrow fix scoped to one confirmed miss (eval_006).
"""

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = Path("data/chunks_v2.json")
MODEL_NAME = "all-MiniLM-L6-v2"

# Hand-written, content-verified descriptive prefix per chunk id. Values
# checked directly against the chunk's own table text before writing.
ENRICHMENT_PREFIXES = {
    602: (
        "Levi Strauss & Co. net income for fiscal year 2025 was $578.1 million, "
        "compared to $210.6 million for fiscal year 2024, a 174.5% increase."
    ),
}


def main() -> None:
    load_dotenv()

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    client = create_client(url, key)
    logger.info("Supabase client initialised (service role).")

    all_chunks = json.loads(CHUNKS_PATH.read_text(encoding="utf-8"))
    chunks_by_id = {c["id"]: c for c in all_chunks}

    logger.info("Loading model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    for chunk_id, prefix in ENRICHMENT_PREFIXES.items():
        chunk = chunks_by_id[chunk_id]
        enriched_text = f"{prefix} {chunk['text']}"
        embedding = model.encode(enriched_text)
        client.table("chunks").update({"embedding": embedding.tolist()}).eq("id", chunk_id).execute()
        logger.info("Updated chunk %d embedding in Supabase (targeted prefix).", chunk_id)

    print(f"\nRe-embedded {len(ENRICHMENT_PREFIXES)} chunk(s): {list(ENRICHMENT_PREFIXES)}")


if __name__ == "__main__":
    main()
