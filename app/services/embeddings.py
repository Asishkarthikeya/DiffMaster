"""Gemini embeddings using the new google.genai SDK."""

import logging
from google import genai

from app.core.config import settings

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "gemini-embedding-exp-03-07"
EMBEDDING_DIM = 768

# Initialize client
_client = None
if settings.GEMINI_API_KEY:
    _client = genai.Client(api_key=settings.GEMINI_API_KEY)


def get_embedding(text: str) -> list[float]:
    """Get embedding vector for a text snippet using Gemini."""
    if not _client:
        logger.warning("No GEMINI_API_KEY set. Returning zero vector.")
        return [0.0] * EMBEDDING_DIM

    try:
        text = text.replace("\n", " ")[:8000]
        result = _client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return [0.0] * EMBEDDING_DIM


def get_query_embedding(text: str) -> list[float]:
    """Get embedding optimized for search queries."""
    if not _client:
        return [0.0] * EMBEDDING_DIM

    try:
        text = text.replace("\n", " ")[:2000]
        result = _client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
        )
        return result.embeddings[0].values
    except Exception as e:
        logger.error(f"Query embedding failed: {e}")
        return [0.0] * EMBEDDING_DIM
