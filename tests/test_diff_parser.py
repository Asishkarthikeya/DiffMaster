"""Tests for diff parsing and smart chunking."""

import pytest

from app.integrations.base import DiffHunk
from app.services.diff_parser import (
    ChunkedDiff,
    TokenizedHunk,
    classify_diff_lines,
    compute_content_hash,
    count_tokens,
    smart_chunk,
    tokenize_hunks,
    calculate_risk_score,
)


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_simple_string(self):
        tokens = count_tokens("hello world")
        assert tokens > 0

    def test_code_snippet(self):
        code = "def authenticate(user, password):\n    return check(user, password)"
        tokens = count_tokens(code)
        assert tokens > 5


class TestComputeContentHash:
    def test_deterministic(self):
        h1 = compute_content_hash("hello")
        h2 = compute_content_hash("hello")
        assert h1 == h2

    def test_different_content(self):
        h1 = compute_content_hash("hello")
        h2 = compute_content_hash("world")
        assert h1 != h2

    def test_hash_length(self):
        h = compute_content_hash("test")
        assert len(h) == 16


class TestClassifyDiffLines:
    def test_classify_added_removed_context(self):
        content = (
            " context line\n"
            "+added line\n"
            "-removed line\n"
            " another context\n"
        )
        added, removed, context = classify_diff_lines(content)
        assert len(added) == 1
        assert len(removed) == 1
        assert len(context) == 2

    def test_ignores_diff_headers(self):
        content = "--- a/file.py\n+++ b/file.py\n+real add"
        added, removed, context = classify_diff_lines(content)
        assert len(added) == 1
        assert added[0] == "real add"


class TestCalculateRiskScore:
    def test_clean_code_low_risk(self):
        hunk = DiffHunk(
            file_path="readme.md",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+Updated docs"
        )
        score = calculate_risk_score(hunk, ["Updated docs"], [])
        assert score < 0.5

    def test_secret_pattern_high_risk(self):
        hunk = DiffHunk(
            file_path="config.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+api_key = 'secret123'"
        )
        score = calculate_risk_score(hunk, ["api_key = 'secret123'"], [])
        assert score > 0

    def test_eval_pattern_risk(self):
        hunk = DiffHunk(
            file_path="app.py",
            old_start=1, old_count=1, new_start=1, new_count=2,
            content="+result = eval(user_input)"
        )
        score = calculate_risk_score(hunk, ["result = eval(user_input)"], [])
        assert score > 0


class TestTokenizeHunks:
    def test_tokenize_basic_hunks(self, sample_diff_hunks):
        result = tokenize_hunks(sample_diff_hunks)
        assert len(result) == 3
        assert all(isinstance(th, TokenizedHunk) for th in result)
        assert all(th.token_count > 0 for th in result)

    def test_sorted_by_risk_desc(self, sample_diff_hunks):
        result = tokenize_hunks(sample_diff_hunks)
        for i in range(len(result) - 1):
            assert result[i].risk_score >= result[i + 1].risk_score

    def test_skips_binary_files(self):
        hunks = [
            DiffHunk(
                file_path="image.png",
                old_start=0, old_count=0, new_start=0, new_count=0,
                content="Binary files differ",
                is_binary=True,
            )
        ]
        result = tokenize_hunks(hunks)
        assert len(result) == 0

    def test_content_hash_populated(self, sample_diff_hunks):
        result = tokenize_hunks(sample_diff_hunks)
        for th in result:
            assert th.content_hash != ""
            assert len(th.content_hash) == 16


class TestSmartChunk:
    def test_single_chunk_small_diff(self, sample_diff_hunks):
        tokenized = tokenize_hunks(sample_diff_hunks)
        chunked = smart_chunk(tokenized, max_tokens_per_chunk=10000)
        assert isinstance(chunked, ChunkedDiff)
        assert chunked.total_hunks == 3
        assert chunked.files_changed == 3
        assert len(chunked.chunks) >= 1

    def test_splits_on_token_limit(self, sample_diff_hunks):
        tokenized = tokenize_hunks(sample_diff_hunks)
        chunked = smart_chunk(tokenized, max_tokens_per_chunk=10)
        assert len(chunked.chunks) > 1

    def test_oversized_hunk_gets_own_chunk(self):
        big_content = "+line\n" * 500
        hunks = [
            DiffHunk(
                file_path="big.py",
                old_start=1, old_count=1, new_start=1, new_count=500,
                content=big_content,
            )
        ]
        tokenized = tokenize_hunks(hunks)
        chunked = smart_chunk(tokenized, max_tokens_per_chunk=50)
        assert len(chunked.chunks) == 1
        assert len(chunked.chunks[0]) == 1
