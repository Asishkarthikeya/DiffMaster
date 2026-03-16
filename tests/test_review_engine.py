"""Tests for the review engine."""

import json

import pytest

from app.services.review_engine import (
    AIReviewFinding,
    _build_chunk_prompt,
    _parse_ai_response,
)
from app.integrations.base import DiffHunk
from app.services.diff_parser import TokenizedHunk, tokenize_hunks
from app.services.blast_radius import BlastRadiusReport, ImpactedSymbol, SecurityBoundary
from app.parsing.tree_sitter_parser import CodeSymbol


class TestBuildChunkPrompt:
    def test_basic_prompt(self, sample_diff_hunks):
        tokenized = tokenize_hunks(sample_diff_hunks)
        prompt = _build_chunk_prompt(tokenized)
        assert "Code Diff to Review" in prompt
        assert "app/auth.py" in prompt
        assert "Risk Score" in prompt

    def test_with_blast_radius(self, sample_diff_hunks):
        tokenized = tokenize_hunks(sample_diff_hunks)
        blast = BlastRadiusReport(
            impacted_symbols=[
                ImpactedSymbol(
                    symbol=CodeSymbol(
                        name="authenticate",
                        kind="function",
                        file_path="auth.py",
                        start_line=10,
                        end_line=20,
                    ),
                    file_path="auth.py",
                    risk_level="high",
                    reason="Modified auth function",
                )
            ],
            security_boundaries=[
                SecurityBoundary(
                    file_path="auth.py",
                    boundary_type="auth",
                    line=10,
                    description="Authentication boundary",
                )
            ],
        )
        prompt = _build_chunk_prompt(tokenized, blast_radius=blast)
        assert "Blast Radius Context" in prompt
        assert "authenticate" in prompt
        assert "Security Boundaries" in prompt

    def test_with_rag_context(self, sample_diff_hunks):
        tokenized = tokenize_hunks(sample_diff_hunks)
        rag = [
            {
                "severity": "WARNING",
                "title": "Similar issue",
                "file_path": "other.py",
                "body": "Previously found similar pattern",
            }
        ]
        prompt = _build_chunk_prompt(tokenized, rag_context=rag)
        assert "Similar Past Findings" in prompt


class TestParseAIResponse:
    def test_valid_json_array(self):
        response = json.dumps([
            {
                "severity": "BLOCKER",
                "category": "security",
                "file_path": "app.py",
                "line_start": 10,
                "line_end": 15,
                "title": "SQL Injection",
                "body": "Unsafe query",
                "suggestion": "Use parameterized",
                "evidence": "f-string in query",
            }
        ])
        findings = _parse_ai_response(response)
        assert len(findings) == 1
        assert findings[0].severity == "BLOCKER"
        assert findings[0].title == "SQL Injection"

    def test_json_with_surrounding_text(self):
        response = 'Here are the findings:\n[{"severity": "INFO", "category": "maintainability", "file_path": "x.py", "line_start": 1, "line_end": 1, "title": "test", "body": "test"}]\nEnd.'
        findings = _parse_ai_response(response)
        assert len(findings) == 1

    def test_empty_array(self):
        findings = _parse_ai_response("[]")
        assert len(findings) == 0

    def test_invalid_json(self):
        findings = _parse_ai_response("not json at all")
        assert len(findings) == 0

    def test_no_brackets(self):
        findings = _parse_ai_response("No issues found in this code.")
        assert len(findings) == 0

    def test_missing_fields_uses_defaults(self):
        response = json.dumps([{"severity": "WARNING"}])
        findings = _parse_ai_response(response)
        assert len(findings) == 1
        assert findings[0].category == "maintainability"
        assert findings[0].file_path == ""
