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
from utils import is_out_of_scope

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
TOP_K = 10

# OUT_OF_SCOPE_THRESHOLD: set to 0.20 — intercepts only
# truly empty retrievals (no chunks returned or all chunks
# below meaningful similarity). A value of 0.53 was tested
# in Week 2 Task 8 and caused 2 HIT regressions because
# qualitative in-scope questions cluster at 0.37–0.55,
# overlapping the OOS zone. Full OOS detection deferred to
# post-FastAPI (open item #12). See data/rrf_tuning_results.md.
OUT_OF_SCOPE_THRESHOLD = 0.20


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

    if is_out_of_scope(hits, OUT_OF_SCOPE_THRESHOLD):
        print("\nANSWER")
        print("-" * 6)
        print("This question cannot be answered from the available Levi Strauss SEC filings and transcripts.")
        print("\nCLAIMS")
        print("-" * 6)
        print('[1] "No answer found in corpus."')
        print("    Tier: Not-in-corpus")
        print("    Chunk: -1 | FY: N/A")
        return

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)

    result = tag_claims(question, hits, model)
    _print_result(result, hits)


if __name__ == "__main__":
    main()
