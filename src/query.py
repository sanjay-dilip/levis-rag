"""Answer questions about Levi's SEC filings using hybrid retrieval and Gemini."""

import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

from dotenv import load_dotenv
import google.generativeai as genai

from retrieve import build_retriever
from tier_tagger import tag_claims

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
TOP_K = 10


def _print_result(result: dict, hits: list[dict]) -> None:
    """Print the structured tier-tagged answer followed by retrieval debug info."""
    print("\nANSWER")
    print("-" * 6)
    print(result.get("answer", ""))

    print("\nCLAIMS")
    print("-" * 6)
    for i, claim in enumerate(result.get("claims", []), start=1):
        fy = claim.get("fiscal_year") or "N/A"
        print(f'[{i}] "{claim["claim_text"]}"')
        print(f'    Tier: {claim["tier"]}')
        print(f'    Chunk: {claim["supporting_chunk_id"]} | FY: {fy}')

    print("\nRETRIEVAL DEBUG")
    print("-" * 15)
    for rank, chunk in enumerate(hits, start=1):
        print(
            f"\n[Chunk {rank}] (id={chunk['id']}, bm25={chunk['bm25_rank']}, "
            f"dense={chunk['dense_rank']}, rrf={chunk['rrf_score']:.4f})"
        )
        text = chunk["text"]
        print(text[:300] + "..." if len(text) > 300 else text)


def main() -> None:
    """Run the full RAG query pipeline."""
    if len(sys.argv) < 2:
        print('Usage: python src/query.py "your question here"')
        sys.exit(1)

    question = sys.argv[1]

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")

    retriever = build_retriever()
    hits = retriever.retrieve(question, top_k=TOP_K)

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    result = tag_claims(question, hits, model)
    _print_result(result, hits)


if __name__ == "__main__":
    main()
