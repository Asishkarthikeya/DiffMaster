"""Tests for comment generation and deduplication."""

from unittest.mock import patch

from app.services.comment_generator import (
    FormattedComment,
    _compute_hash,
    _severity_emoji,
    format_for_vcs,
    generate_comments,
    generate_summary,
)
from app.services.policy_engine import PolicyViolation
from app.services.review_engine import AIReviewFinding, ReviewResult


class TestSeverityEmoji:
    def test_blocker(self):
        assert _severity_emoji("BLOCKER") == "\u26d4"

    def test_warning(self):
        assert _severity_emoji("WARNING") == "\u26a0\ufe0f"

    def test_info(self):
        assert _severity_emoji("INFO") == "\u2139\ufe0f"

    def test_unknown(self):
        assert _severity_emoji("UNKNOWN") == "\u2139\ufe0f"


class TestComputeHash:
    def test_deterministic(self):
        h1 = _compute_hash("file.py", "BLOCKER", "Secret found", 10)
        h2 = _compute_hash("file.py", "BLOCKER", "Secret found", 10)
        assert h1 == h2

    def test_different_inputs(self):
        h1 = _compute_hash("file.py", "BLOCKER", "Secret found", 10)
        h2 = _compute_hash("file.py", "WARNING", "Secret found", 10)
        assert h1 != h2


class TestGenerateComments:
    def _make_review_result(self, findings=None, violations=None):
        return ReviewResult(
            findings=findings or [],
            policy_violations=violations or [],
        )

    def test_empty_review(self):
        result = self._make_review_result()
        comments = generate_comments(result)
        assert len(comments) == 0

    def test_findings_converted(self):
        findings = [
            AIReviewFinding(
                severity="BLOCKER",
                category="security",
                file_path="app.py",
                line_start=10,
                line_end=15,
                title="SQL Injection",
                body="User input concatenated into SQL query",
                suggestion="Use parameterized queries",
                evidence="query = f'SELECT * FROM users WHERE id={user_id}'",
            )
        ]
        result = self._make_review_result(findings=findings)
        comments = generate_comments(result)
        assert len(comments) == 1
        assert comments[0].severity == "BLOCKER"
        assert comments[0].title == "SQL Injection"

    def test_policy_violations_converted(self):
        violations = [
            PolicyViolation(
                rule_name="builtin_secret_detection",
                rule_type="secret_detection",
                severity="BLOCKER",
                file_path="config.py",
                line=5,
                message="Hardcoded password",
                evidence="password = 'abc'",
                suggestion="Use env vars",
            )
        ]
        result = self._make_review_result(violations=violations)
        comments = generate_comments(result)
        assert len(comments) == 1
        assert "Policy" in comments[0].title

    def test_deduplication(self):
        finding = AIReviewFinding(
            severity="WARNING", category="performance",
            file_path="app.py", line_start=10, line_end=10,
            title="N+1 query", body="Found N+1 pattern",
        )
        result = self._make_review_result(findings=[finding, finding])
        comments = generate_comments(result)
        assert len(comments) == 1

    def test_existing_hash_dedup(self):
        finding = AIReviewFinding(
            severity="WARNING", category="performance",
            file_path="app.py", line_start=10, line_end=10,
            title="N+1 query", body="Found N+1 pattern",
        )
        result = self._make_review_result(findings=[finding])
        all_comments = generate_comments(result)
        existing = {all_comments[0].content_hash}
        comments = generate_comments(result, existing_hashes=existing)
        assert len(comments) == 0

    @patch("app.services.comment_generator.settings")
    def test_max_comments_cap(self, mock_settings):
        mock_settings.max_comments_per_pr = 2
        mock_settings.min_severity = "INFO"
        mock_settings.suppress_style_only = False

        findings = [
            AIReviewFinding(
                severity="WARNING", category="performance",
                file_path=f"file{i}.py", line_start=i, line_end=i,
                title=f"Issue {i}", body=f"Body {i}",
            )
            for i in range(5)
        ]
        result = self._make_review_result(findings=findings)
        comments = generate_comments(result)
        assert len(comments) == 2

    def test_sorted_by_severity(self):
        findings = [
            AIReviewFinding(
                severity="INFO", category="maintainability",
                file_path="a.py", line_start=1, line_end=1,
                title="Info issue", body="Info",
            ),
            AIReviewFinding(
                severity="BLOCKER", category="security",
                file_path="b.py", line_start=2, line_end=2,
                title="Blocker issue", body="Blocker",
            ),
            AIReviewFinding(
                severity="WARNING", category="performance",
                file_path="c.py", line_start=3, line_end=3,
                title="Warning issue", body="Warning",
            ),
        ]
        result = self._make_review_result(findings=findings)
        comments = generate_comments(result)
        assert comments[0].severity == "BLOCKER"
        assert comments[1].severity == "WARNING"
        assert comments[2].severity == "INFO"


class TestGenerateSummary:
    def test_summary_with_findings(self):
        comments = [
            FormattedComment(
                file_path="app.py", line_start=10, line_end=10,
                severity="BLOCKER", category="security",
                title="Secret exposed", body="Found secret",
                suggestion="", evidence="", content_hash="abc",
            ),
            FormattedComment(
                file_path="utils.py", line_start=20, line_end=20,
                severity="WARNING", category="performance",
                title="Slow query", body="N+1 pattern",
                suggestion="", evidence="", content_hash="def",
            ),
        ]
        summary = generate_summary(comments)
        assert "DiffMaster Review Summary" in summary
        assert "BLOCKER" in summary
        assert "WARNING" in summary
        assert "Action Required" in summary

    def test_summary_empty(self):
        summary = generate_summary([])
        assert "DiffMaster Review Summary" in summary

    def test_summary_truncation(self):
        comments = [
            FormattedComment(
                file_path=f"file{i}.py", line_start=i, line_end=i,
                severity="INFO", category="maintainability",
                title=f"Issue {i}", body=f"Body {i}",
                suggestion="", evidence="", content_hash=f"hash{i}",
            )
            for i in range(15)
        ]
        summary = generate_summary(comments)
        assert "more" in summary


class TestFormatForVcs:
    def test_format_includes_severity(self):
        comment = FormattedComment(
            file_path="app.py", line_start=10, line_end=10,
            severity="BLOCKER", category="security",
            title="SQL Injection", body="Unsafe query",
            suggestion="Use parameterized queries",
            evidence="query = f'SELECT ...'",
            content_hash="abc123",
        )
        formatted = format_for_vcs(comment)
        assert "[BLOCKER]" in formatted
        assert "SQL Injection" in formatted
        assert "Evidence" in formatted
        assert "Suggested Fix" in formatted
        assert "DiffMaster" in formatted
