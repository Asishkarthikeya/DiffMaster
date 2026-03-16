"""Diff parsing, hunk extraction, and smart chunking with token counting."""

import hashlib
from dataclasses import dataclass, field

import structlog
import tiktoken

from app.integrations.base import DiffHunk

logger = structlog.get_logger()

_encoding = tiktoken.get_encoding("cl100k_base")


@dataclass
class TokenizedHunk:
    hunk: DiffHunk
    token_count: int
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)
    context_lines: list[str] = field(default_factory=list)
    content_hash: str = ""
    risk_score: float = 0.0


@dataclass
class ChunkedDiff:
    chunks: list[list[TokenizedHunk]]
    total_tokens: int
    total_hunks: int
    files_changed: int


def count_tokens(text: str) -> int:
    return len(_encoding.encode(text))


def compute_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def classify_diff_lines(content: str) -> tuple[list[str], list[str], list[str]]:
    added, removed, context = [], [], []
    for line in content.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
        else:
            context.append(line)
    return added, removed, context


def calculate_risk_score(hunk: DiffHunk, added: list[str], removed: list[str]) -> float:
    """Heuristic risk score [0.0 - 1.0] based on hunk characteristics."""
    score = 0.0
    total_changes = len(added) + len(removed)
    if total_changes == 0:
        return 0.0

    if total_changes > 50:
        score += 0.3
    elif total_changes > 20:
        score += 0.15

    risk_patterns = [
        "password", "secret", "token", "api_key", "apikey", "private_key",
        "eval(", "exec(", "subprocess", "os.system", "shell=True",
        "innerHTML", "dangerouslySetInnerHTML",
        "SELECT ", "INSERT ", "DELETE ", "UPDATE ", "DROP ",
        "sql", "query",
    ]
    all_added = "\n".join(added).lower()
    for pattern in risk_patterns:
        if pattern.lower() in all_added:
            score += 0.15

    if hunk.is_new_file:
        score += 0.1

    return min(score, 1.0)


def tokenize_hunks(hunks: list[DiffHunk]) -> list[TokenizedHunk]:
    result = []
    for hunk in hunks:
        if hunk.is_binary:
            continue
        token_count = count_tokens(hunk.content)
        added, removed, context = classify_diff_lines(hunk.content)
        risk = calculate_risk_score(hunk, added, removed)
        result.append(
            TokenizedHunk(
                hunk=hunk,
                token_count=token_count,
                added_lines=added,
                removed_lines=removed,
                context_lines=context,
                content_hash=compute_content_hash(hunk.content),
                risk_score=risk,
            )
        )
    result.sort(key=lambda h: h.risk_score, reverse=True)
    return result


def smart_chunk(
    tokenized_hunks: list[TokenizedHunk],
    max_tokens_per_chunk: int = 6000,
) -> ChunkedDiff:
    """Group hunks into LLM-friendly chunks respecting token limits."""
    chunks: list[list[TokenizedHunk]] = []
    current_chunk: list[TokenizedHunk] = []
    current_tokens = 0
    files = set()

    for th in tokenized_hunks:
        files.add(th.hunk.file_path)
        if th.token_count > max_tokens_per_chunk:
            if current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_tokens = 0
            chunks.append([th])
            continue

        if current_tokens + th.token_count > max_tokens_per_chunk:
            chunks.append(current_chunk)
            current_chunk = [th]
            current_tokens = th.token_count
        else:
            current_chunk.append(th)
            current_tokens += th.token_count

    if current_chunk:
        chunks.append(current_chunk)

    total_tokens = sum(th.token_count for th in tokenized_hunks)
    return ChunkedDiff(
        chunks=chunks,
        total_tokens=total_tokens,
        total_hunks=len(tokenized_hunks),
        files_changed=len(files),
    )
