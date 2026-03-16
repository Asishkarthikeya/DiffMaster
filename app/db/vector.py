"""pgvector helper utilities."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_pgvector_extension(session: AsyncSession) -> None:
    await session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    await session.commit()
