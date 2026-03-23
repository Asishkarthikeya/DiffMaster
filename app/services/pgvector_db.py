"""
pgvector-backed Vector DB for DiffMaster.
Alternative to the in-memory FAISS index for persistent, production deployments.

Requires:
    DATABASE_URL env var pointing to a PostgreSQL database with pgvector extension.
    USE_PGVECTOR=true in environment.

Usage:
    from app.services.pgvector_db import PgVectorIndex, build_pgvector_index

    # Build index (indexes codebase into PostgreSQL)
    index = build_pgvector_index(vcs_client, repo, ref, max_files=50)

    # Search
    results = index.search("authentication logic", top_k=5)
"""

import logging
from typing import Optional

logger = logging.getLogger("diffmaster.pgvector")

EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 dimension


def _get_engine():
    """Create SQLAlchemy engine from DATABASE_URL."""
    from sqlalchemy import create_engine
    from app.core.config import settings

    if not settings.DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is required for pgvector. "
            "Set USE_PGVECTOR=false to use FAISS instead."
        )
    return create_engine(settings.DATABASE_URL)


def ensure_tables(engine) -> None:
    """
    Create the pgvector extension and code_embeddings table if they don't exist.
    Safe to call multiple times (idempotent).
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS code_embeddings (
                id SERIAL PRIMARY KEY,
                repo TEXT NOT NULL,
                file_path TEXT NOT NULL,
                node_name TEXT,
                node_type TEXT,
                content TEXT,
                embedding vector({EMBEDDING_DIM}),
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_code_embeddings_repo
            ON code_embeddings (repo)
        """))
    logger.info("pgvector tables ensured")


class PgVectorIndex:
    """
    PostgreSQL + pgvector code search index.
    Interface-compatible with the FAISS CodebaseIndex in rag.py.

    Methods:
        add_chunk(text, metadata) — embed and store a code chunk
        search(query, top_k) — semantic similarity search
        size — number of indexed chunks
    """

    def __init__(self, engine, repo: str):
        self._engine = engine
        self._repo = repo
        self._count = 0

    def add_chunk(
        self,
        text: str,
        metadata: dict,
    ) -> None:
        """
        Embed a code chunk and store it in PostgreSQL with pgvector.

        Args:
            text: The code snippet to embed
            metadata: Dict with file_path, node_name, node_type, content
        """
        from sqlalchemy import text as sql_text
        from app.services.embeddings import get_embedding

        embedding = get_embedding(text)
        if all(v == 0.0 for v in embedding):
            logger.debug(f"Skipping zero embedding for {metadata.get('node_name', '?')}")
            return

        embedding_str = "[" + ",".join(str(v) for v in embedding) + "]"

        with self._engine.begin() as conn:
            conn.execute(
                sql_text("""
                    INSERT INTO code_embeddings
                        (repo, file_path, node_name, node_type, content, embedding)
                    VALUES
                        (:repo, :file_path, :node_name, :node_type, :content, :embedding)
                """),
                {
                    "repo": self._repo,
                    "file_path": metadata.get("file_path", ""),
                    "node_name": metadata.get("node_name", ""),
                    "node_type": metadata.get("node_type", ""),
                    "content": metadata.get("content", text)[:5000],
                    "embedding": embedding_str,
                },
            )
        self._count += 1

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Semantic similarity search using pgvector cosine distance.

        Args:
            query: Natural language search query
            top_k: Number of results to return

        Returns:
            List of dicts with file_path, node_name, node_type, content, score
        """
        from sqlalchemy import text as sql_text
        from app.services.embeddings import get_query_embedding

        query_embedding = get_query_embedding(query)
        embedding_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

        with self._engine.connect() as conn:
            rows = conn.execute(
                sql_text("""
                    SELECT
                        file_path, node_name, node_type, content,
                        1 - (embedding <=> :embedding::vector) AS score
                    FROM code_embeddings
                    WHERE repo = :repo
                    ORDER BY embedding <=> :embedding::vector
                    LIMIT :top_k
                """),
                {
                    "embedding": embedding_str,
                    "repo": self._repo,
                    "top_k": top_k,
                },
            ).fetchall()

        return [
            {
                "file_path": row[0],
                "node_name": row[1],
                "node_type": row[2],
                "content": row[3],
                "score": float(row[4]),
            }
            for row in rows
        ]

    @property
    def size(self) -> int:
        """Number of chunks added in this session."""
        return self._count

    def clear_repo(self) -> int:
        """
        Delete all embeddings for the current repo.
        Useful for re-indexing on new PR events.

        Returns:
            Number of rows deleted.
        """
        from sqlalchemy import text as sql_text

        with self._engine.begin() as conn:
            result = conn.execute(
                sql_text("DELETE FROM code_embeddings WHERE repo = :repo"),
                {"repo": self._repo},
            )
        deleted = result.rowcount
        logger.info(f"Cleared {deleted} embeddings for {self._repo}")
        return deleted


def build_pgvector_index(
    gh_client,
    repo_name: str,
    ref: str,
    max_files: int = 50,
) -> PgVectorIndex:
    """
    Build a pgvector codebase index by fetching repo files and indexing them.
    Mirrors build_codebase_index() from rag.py but stores in PostgreSQL.

    Args:
        gh_client: VCS client (GitHub/GitLab/Bitbucket)
        repo_name: Repository full name
        ref: Git ref (branch or commit SHA)
        max_files: Max files to index

    Returns:
        PgVectorIndex ready for searching
    """
    from app.services.parser import get_modified_functions

    engine = _get_engine()
    ensure_tables(engine)

    index = PgVectorIndex(engine, repo_name)

    # Clear old embeddings for this repo before re-indexing
    index.clear_repo()

    # Fetch repo tree
    try:
        if hasattr(gh_client, "get_repo"):
            # GitHub client
            repo_obj = gh_client.get_repo(repo_name)
            tree = repo_obj.get_git_tree(ref, recursive=True)
            code_files = [
                item.path for item in tree.tree
                if item.type == "blob"
                and item.path.endswith((".py", ".js", ".ts", ".jsx", ".tsx"))
                and item.size < 50000
            ][:max_files]
        else:
            # GitLab/Bitbucket — list files via API
            code_files = []
            logger.warning("pgvector indexing for non-GitHub VCS not yet optimized")
            return index
    except Exception as e:
        logger.error(f"Failed to fetch repo tree for pgvector indexing: {e}")
        return index

    for file_path in code_files:
        try:
            content = gh_client.get_file_content(repo_name, file_path, ref=ref)
            if not content or len(content) > 50000:
                continue

            # Extract AST nodes
            functions = get_modified_functions(
                content, file_path,
                [{"line_num": i + 1, "content": line} for i, line in enumerate(content.splitlines())]
            )

            for func in functions:
                func_content = func.get("content", "")
                if not func_content or len(func_content) > 3000:
                    continue
                index.add_chunk(func_content, {
                    "file_path": file_path,
                    "node_name": func.get("node_name", "unknown"),
                    "node_type": func.get("node_type", "function"),
                    "content": func_content,
                })

        except Exception as e:
            logger.warning(f"Skipping {file_path}: {e}")

    logger.info(f"pgvector index built: {index.size} chunks for {repo_name}")
    return index
