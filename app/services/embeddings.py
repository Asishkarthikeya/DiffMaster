import logging
import google.generativeai as genai
from app.core.config import settings

logger = logging.getLogger(__name__)

# Configure Gemini
if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)

EMBEDDING_MODEL = "models/text-embedding-004"
EMBEDDING_DIM = 768


def get_embedding(text: str) -> list[float]:
    """Get embedding vector for a text snippet using Gemini."""
    if not settings.GEMINI_API_KEY:
        logger.warning("No GEMINI_API_KEY set. Returning zero vector.")
        return [0.0] * EMBEDDING_DIM

    try:
        text = text.replace("\n", " ")[:8000]  # Truncate to avoid token limits
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=text,
            task_type="retrieval_document"
        )
        return result["embedding"]
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return [0.0] * EMBEDDING_DIM


def get_query_embedding(text: str) -> list[float]:
    """Get embedding optimized for search queries."""
    if not settings.GEMINI_API_KEY:
        return [0.0] * EMBEDDING_DIM

    try:
        text = text.replace("\n", " ")[:2000]
        result = genai.embed_content(
            model=EMBEDDING_MODEL,
            content=text,
            task_type="retrieval_query"
        )
        return result["embedding"]
    except Exception as e:
        logger.error(f"Query embedding failed: {e}")
        return [0.0] * EMBEDDING_DIM
