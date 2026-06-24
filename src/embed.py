"""Generate sentence embeddings for every chunk and persist them as a numpy array."""

import json
import logging
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CHUNKS_PATH = Path("data/chunks.json")
EMBEDDINGS_PATH = Path("data/embeddings.npy")
MODEL_NAME = "all-MiniLM-L6-v2"


def load_texts(path: Path) -> list[str]:
    """Load chunks.json and return the text field from every chunk."""
    chunks = json.loads(path.read_text(encoding="utf-8"))
    return [chunk["text"] for chunk in chunks]


def embed(texts: list[str], model_name: str) -> np.ndarray:
    """Encode *texts* with *model_name* and return the embedding matrix."""
    logger.info("Loading model: %s", model_name)
    model = SentenceTransformer(model_name)
    logger.info("Encoding %d chunks...", len(texts))
    return model.encode(texts, show_progress_bar=True)


def main() -> None:
    """Load chunks, embed texts, save embeddings, and print the shape."""
    texts = load_texts(CHUNKS_PATH)
    logger.info("Loaded %d texts from %s", len(texts), CHUNKS_PATH)

    embeddings = embed(texts, MODEL_NAME)

    EMBEDDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.save(EMBEDDINGS_PATH, embeddings)
    logger.info("Saved embeddings to %s", EMBEDDINGS_PATH)

    print(f"Embeddings shape: {embeddings.shape}")


if __name__ == "__main__":
    main()
