"""Answer questions about Levi's SEC filings using hybrid retrieval and Gemini."""

import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

from dotenv import load_dotenv
import google.generativeai as genai

from retrieve import build_retriever

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
TOP_K = 10

PROMPT_TEMPLATE = """\
You are a financial analyst answering questions about Levi Strauss & Co. \
based solely on excerpts from SEC filings.

Answer the question using ONLY the context provided. For each fact you \
state, cite the chunk number in brackets like [Chunk 3]. If the answer \
is not in the context, say "Not found in provided context."

Context:
{context}

Question: {question}"""


def build_prompt(question: str, hits: list[dict]) -> str:
    """Assemble the RAG prompt from the question and retrieved chunks."""
    context_lines = [
        f"[Chunk {rank}]: {chunk['text']}"
        for rank, chunk in enumerate(hits, start=1)
    ]
    return PROMPT_TEMPLATE.format(
        context="\n\n".join(context_lines),
        question=question,
    )


def call_gemini(prompt: str, api_key: str) -> str:
    """Send *prompt* to Gemini and return the response text."""
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text


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

    prompt = build_prompt(question, hits)
    answer = call_gemini(prompt, api_key)

    print(answer)
    print("\n---")
    for rank, chunk in enumerate(hits, start=1):
        print(
            f"\n[Chunk {rank}] (id={chunk['id']}, bm25={chunk['bm25_rank']}, "
            f"dense={chunk['dense_rank']}, rrf={chunk['rrf_score']:.4f})"
        )
        text = chunk["text"]
        print(text[:300] + "..." if len(text) > 300 else text)


if __name__ == "__main__":
    main()
