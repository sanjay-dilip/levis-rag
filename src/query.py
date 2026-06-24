"""Embed a question, retrieve the top-5 chunks by cosine similarity, and answer via Gemini."""

import json
import logging
import os
import sys
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

import numpy as np
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer
import google.generativeai as genai

# KNOWN LIMITATION:
# Dense retrieval underperforms on financial tables. Chunk 77 contains
# Levi's DTC revenue figure ($3.07B) but scores below top-10 similarity
# for the query "DTC revenue" because the chunk is number-dense and
# semantically sparse. Fix: hybrid sparse+dense retrieval
# (BM25 keyword layer + pgvector dense layer) or section-aware chunking
# that keeps financial statement tables as discrete chunks.

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = "data/chunks.json"
EMBEDDINGS_PATH = "data/embeddings.npy"
MODEL_NAME = "all-MiniLM-L6-v2"
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


def load_chunks(path: str) -> list[dict]:
    """Load and return the list of chunk dicts from chunks.json."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cosine_similarity(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Return cosine similarity scores between *query_vec* and every row in *matrix*."""
    query_norm = query_vec / np.linalg.norm(query_vec)
    row_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normed_matrix = matrix / row_norms
    return normed_matrix @ query_norm


def retrieve(
    question: str,
    model: SentenceTransformer,
    chunks: list[dict],
    embeddings: np.ndarray,
    top_k: int,
) -> list[tuple[dict, float]]:
    """Embed *question* and return the top-k (chunk, score) pairs by cosine similarity."""
    query_vec = model.encode(question)
    scores = cosine_similarity(query_vec, embeddings)
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(chunks[i], float(scores[i])) for i in top_indices]


def build_prompt(question: str, hits: list[tuple[dict, float]]) -> str:
    """Assemble the RAG prompt from the question and retrieved chunks."""
    context_lines = [
        f"[Chunk {rank}]: {chunk['text']}"
        for rank, (chunk, _) in enumerate(hits, start=1)
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
        print("Usage: python src/query.py \"your question here\"")
        sys.exit(1)

    question = sys.argv[1]

    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")

    chunks = load_chunks(CHUNKS_PATH)
    embeddings = np.load(EMBEDDINGS_PATH)

    logger.info("Loading model: %s", MODEL_NAME)
    model = SentenceTransformer(MODEL_NAME)

    hits = retrieve(question, model, chunks, embeddings, TOP_K)
    prompt = build_prompt(question, hits)
    answer = call_gemini(prompt, api_key)

    print(answer)
    print("\n---")
    for rank, (chunk, score) in enumerate(hits, start=1):
        print(f"\n[Chunk {rank}] (id={chunk['id']}, score={score:.4f})")
        print(chunk["text"][:300] + "..." if len(chunk["text"]) > 300 else chunk["text"])


if __name__ == "__main__":
    main()
