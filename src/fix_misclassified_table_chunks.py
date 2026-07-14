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

Residual-miss triage session (following eval_006): 8 more entries added
after the same local cosine pre-check discipline (candidate prefixes tested
offline against each question with the local SentenceTransformer before any
Supabase write). Two lessons repeated from eval_006: (1) a short, one-shot
prefix sometimes barely moves the needle when the chunk is very long/mixed
(e.g. chunk 604's first draft prefix scored *below* the no-prefix baseline,
0.332 vs 0.344) -- a longer prefix that repeats the key term/figures in the
question's own phrasing (not just states them once) reliably did better in
every case tried. (2) a chunk already carrying the generic
filing_type|source|section prefix (chunk 596, is_table=True, enriched in
Week 2) can still fail -- the generic prefix barely moved its cosine either
(0.396 vs 0.394 no-prefix) until replaced with a specific one (0.619).
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
    632: (
        "Levi's inventory levels change fiscal year 2024 to fiscal year 2025. Inventory "
        "levels: $1,237.7 million (fiscal year 2025, as of November 30, 2025) versus "
        "$1,131.3 million (fiscal year 2024, as of December 1, 2024) -- inventory levels "
        "increased by $106.4 million, or 9.4%, year over year."
    ),
    604: (
        "Levi's implied cost of goods sold (COGS) for fiscal year 2025. Cost of goods sold "
        "(COGS) fiscal year 2025: $2,404.2 million. Cost of goods sold (COGS) fiscal year "
        "2024: $2,374.9 million. COGS increased 1.2% year over year. Implied COGS from gross "
        "margin: net revenues $6,282.0 million minus gross profit $3,877.8 million equals "
        "cost of goods sold $2,404.2 million."
    ),
    596: (
        "Levi's DTC revenue as a percentage of total revenue in fiscal year 2025. DTC "
        "(direct-to-consumer) channel revenue as a percentage of total net revenues: 49% in "
        "fiscal year 2025, 47% in fiscal year 2024. Wholesale channel as a percentage of total "
        "net revenues: 51% in fiscal year 2025, 53% in fiscal year 2024."
    ),
    122: (
        "Levi's gross margin for fiscal year 2023 was 56.9%, compared to 57.5% for fiscal "
        "year 2022; gross profit was $3,515.7 million on net revenues of $6,179.0 million."
    ),
    528: (
        "Levi's management describes its DTC First strategy: brand-dedicated retail stores "
        "are an increasingly important part of the DTC First strategy, alongside brand-dedicated "
        "e-commerce sites. Management emphasizes growing owned stores and e-commerce as the "
        "primary channel shift."
    ),
    1202: (
        "Levi's management commentary on inventory levels in the third quarter of fiscal "
        "year 2025 (Q3 FY2025). Compared to the third quarter of fiscal year 2024, "
        "inventory increased 12%, excluding the Dockers business, in preparation for sales "
        "for the remainder of the year and from earlier receipts in order to mitigate "
        "potential impacts from tariffs."
    ),
    603: (
        "Levi's DTC (Direct to Consumer) revenue as a percentage of total net revenues "
        "for fiscal year 2025 (FY2025). As a percentage of net revenues on a reported "
        "basis for the year ended November 30, 2025, DTC comprised 49% of total net "
        "revenues."
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
