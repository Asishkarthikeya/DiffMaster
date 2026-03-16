"""Vector retrieval using pgvector for RAG-powered context augmentation."""

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.comment import ReviewComment
from app.services.rag.embeddings import generate_embedding

logger = structlog.get_logger()
settings = get_settings()


async def find_similar_comments(
    session: AsyncSession,
    query_text: str,
    repository_id: str | None = None,
    top_k: int | None = None,
    threshold: float | None = None,
) -> list[ReviewComment]:
    """Find semantically similar past review comments using pgvector."""
    top_k = top_k or settings.rag_top_k
    threshold = threshold or settings.vector_similarity_threshold

    query_embedding = await generate_embedding(query_text)

    stmt = (
        select(ReviewComment)
        .where(ReviewComment.embedding.isnot(None))
        .order_by(ReviewComment.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )

    result = await session.execute(stmt)
    comments = list(result.scalars().all())

    return comments


async def find_relevant_code_context(
    session: AsyncSession,
    code_snippet: str,
    top_k: int = 5,
) -> list[dict]:
    """Retrieve relevant code context for a given snippet."""
    embedding = await generate_embedding(code_snippet)

    query = text("""
        SELECT
            rc.file_path,
            rc.title,
            rc.body,
            rc.severity,
            rc.category,
            1 - (rc.embedding <=> :embedding::vector) as similarity
        FROM review_comments rc
        WHERE rc.embedding IS NOT NULL
        ORDER BY rc.embedding <=> :embedding::vector
        LIMIT :limit
    """)

    result = await session.execute(
        query, {"embedding": str(embedding), "limit": top_k}
    )
    rows = result.fetchall()

    return [
        {
            "file_path": row.file_path,
            "title": row.title,
            "body": row.body,
            "severity": row.severity,
            "category": row.category,
            "similarity": row.similarity,
        }
        for row in rows
    ]
