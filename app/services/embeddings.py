"""Local embeddings using sentence-transformers — no API key needed, free & unlimited."""

import logging
import numpy as np

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension
_model = None


def _get_model():
    """Lazy-load the sentence-transformers model."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            logger.info("📦 Loading local embedding model (all-MiniLM-L6-v2)...")
            _model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("✅ Local embedding model loaded.")
        except ImportError:
            logger.error("sentence-transformers not installed. pip install sentence-transformers")
            return None
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            return None
    return _model


def get_embedding(text: str) -> list[float]:
    """Get embedding vector for a text snippet using local model."""
    model = _get_model()
    if not model:
        return [0.0] * EMBEDDING_DIM

    try:
        text = text.replace("\n", " ")[:8000]
        embedding = model.encode(text, show_progress_bar=False)
        return embedding.tolist()
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return [0.0] * EMBEDDING_DIM


def get_query_embedding(text: str) -> list[float]:
    """Get embedding for search queries."""
    model = _get_model()
    if not model:
        return [0.0] * EMBEDDING_DIM

    try:
        text = text.replace("\n", " ")[:2000]
        embedding = model.encode(text, show_progress_bar=False)
        return embedding.tolist()
    except Exception as e:
        logger.error(f"Query embedding failed: {e}")
        return [0.0] * EMBEDDING_DIM
