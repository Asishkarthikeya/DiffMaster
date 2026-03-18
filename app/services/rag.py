"""
In-memory FAISS-based RAG for DiffMaster.
At runtime: fetch repo files → parse with Tree-Sitter → embed → index → query.
"""

import numpy as np
import logging
from typing import Optional

from app.services.embeddings import get_embedding, get_query_embedding, EMBEDDING_DIM
from app.services.parser import get_modified_functions, LANGUAGES

logger = logging.getLogger(__name__)

try:
    import faiss
    FAISS_AVAILABLE = True
except ImportError:
    FAISS_AVAILABLE = False
    logger.warning("faiss-cpu not installed. RAG will be disabled.")


class CodebaseIndex:
    """In-memory FAISS vector index for codebase RAG."""

    def __init__(self):
        self.index = faiss.IndexFlatIP(EMBEDDING_DIM) if FAISS_AVAILABLE else None
        self.chunks: list[dict] = []  # Parallel list of metadata

    def add_chunk(self, file_path: str, node_name: str, node_type: str, content: str, intent: str = ""):
        """Embed and add a code chunk to the index."""
        if not self.index:
            return

        embed_text = f"{node_type} {node_name}: {content}"
        embedding = get_embedding(embed_text)
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)
        self.index.add(vec)

        self.chunks.append({
            "file_path": file_path,
            "node_name": node_name,
            "node_type": node_type,
            "content": content,
            "intent": intent,
        })

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search the index for chunks similar to the query."""
        if not self.index or self.index.ntotal == 0:
            return []

        embedding = get_query_embedding(query)
        vec = np.array([embedding], dtype=np.float32)
        faiss.normalize_L2(vec)

        k = min(top_k, self.index.ntotal)
        scores, indices = self.index.search(vec, k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < 0 or idx >= len(self.chunks):
                continue
            chunk = self.chunks[idx].copy()
            chunk["score"] = float(scores[0][i])
            results.append(chunk)

        return results

    @property
    def size(self) -> int:
        return self.index.ntotal if self.index else 0


def build_codebase_index(gh_client, repo_name: str, ref: str, max_files: int = 50) -> CodebaseIndex:
    """
    Build a FAISS index from the repo's source files.
    Fetches files via GitHub API, parses with Tree-Sitter, embeds, and indexes.
    """
    index = CodebaseIndex()

    if not FAISS_AVAILABLE:
        logger.warning("FAISS not available. Skipping index build.")
        return index

    try:
        repo = gh_client.get_repo(repo_name)
        tree = repo.get_git_tree(ref, recursive=True)

        # Filter to supported code files
        code_files = []
        for item in tree.tree:
            if item.type != "blob":
                continue
            ext = item.path.split(".")[-1] if "." in item.path else ""
            if ext in LANGUAGES:
                code_files.append(item.path)

        # Limit to avoid API rate limits
        code_files = code_files[:max_files]
        logger.info(f"Indexing {len(code_files)} files from {repo_name}...")

        for file_path in code_files:
            try:
                content = gh_client.get_file_content(repo_name, file_path, ref=ref)
                if not content or len(content) > 50000:  # Skip massive files
                    continue

                # Parse into AST chunks
                ext = file_path.split(".")[-1]
                lang = LANGUAGES.get(ext)
                if not lang:
                    continue

                from tree_sitter import Parser
                parser = Parser(lang)
                tree_obj = parser.parse(bytes(content, "utf8"))

                target_types = ["function_definition", "class_definition", "method_definition"]
                _walk_and_index(tree_obj.root_node, content, file_path, target_types, index)

            except Exception as e:
                logger.debug(f"Failed to index {file_path}: {e}")

        logger.info(f"Indexed {index.size} code chunks into FAISS.")

    except Exception as e:
        logger.error(f"Failed to build codebase index: {e}")

    return index


def _walk_and_index(node, file_content: str, file_path: str, target_types: list, index: CodebaseIndex):
    """Recursively walk AST and index function/class definitions."""
    if node.type in target_types:
        node_name = "unknown"
        for child in node.children:
            if child.type == "identifier":
                node_name = file_content[child.start_byte:child.end_byte]
                break

        content = file_content[node.start_byte:node.end_byte]
        if len(content) > 100:  # Only index non-trivial chunks
            index.add_chunk(
                file_path=file_path,
                node_name=node_name,
                node_type=node.type,
                content=content[:3000],  # Truncate very long functions
            )

    for child in node.children:
        _walk_and_index(child, file_content, file_path, target_types, index)
