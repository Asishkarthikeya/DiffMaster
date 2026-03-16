"""Core Review Engine - orchestrates the AI-powered code review pipeline."""

import json
from dataclasses import dataclass, field

import structlog
from openai import AsyncOpenAI

from app.config import get_settings
from app.services.blast_radius import BlastRadiusReport
from app.services.diff_parser import ChunkedDiff, TokenizedHunk
from app.services.policy_engine import PolicyEvaluationResult, PolicyViolation

logger = structlog.get_logger()
settings = get_settings()

SYSTEM_PROMPT = """\
You are DiffMaster, an expert AI code reviewer. You analyze code diffs and \
provide precise, actionable feedback. Your reviews are concise, evidence-based, \
and prioritized by severity.

Review Categories:
- [BLOCKER] Security: Injection risks, authz checks, secret exposure, unsafe deser.
- [WARNING] Reliability/Performance: Concurrency hazards, unbounded retries, N+1
- [INFO] Maintainability: Naming, dead code, missing tests, documentation gaps

Output Format (JSON array):
[
  {
    "severity": "BLOCKER|WARNING|INFO",
    "category": "security|reliability|performance|maintainability",
    "file_path": "path/to/file",
    "line_start": 10,
    "line_end": 15,
    "title": "Brief issue title",
    "body": "Detailed explanation of the issue and why it matters",
    "suggestion": "Concrete code fix or next action",
    "evidence": "The specific code pattern that triggered this finding"
  }
]

Guidelines:
- Only flag real issues; do not generate noise
- Be specific about line numbers
- Provide actionable suggestions with code examples when possible
- Consider the blast radius and security boundary context provided
- Respect the policy violations already identified — do not duplicate them
- If the code looks clean, return an empty array []
"""


@dataclass
class AIReviewFinding:
    severity: str
    category: str
    file_path: str
    line_start: int
    line_end: int
    title: str
    body: str
    suggestion: str = ""
    evidence: str = ""


@dataclass
class ReviewResult:
    findings: list[AIReviewFinding] = field(default_factory=list)
    policy_violations: list[PolicyViolation] = field(default_factory=list)
    total_tokens_used: int = 0
    chunks_processed: int = 0


def _build_chunk_prompt(
    chunk: list[TokenizedHunk],
    blast_radius: BlastRadiusReport | None = None,
    rag_context: list[dict] | None = None,
) -> str:
    parts = ["## Code Diff to Review\n"]

    for th in chunk:
        parts.append(f"### File: {th.hunk.file_path}")
        parts.append(f"Lines {th.hunk.new_start}-{th.hunk.new_start + th.hunk.new_count}")
        parts.append(f"Risk Score: {th.risk_score:.2f}")
        parts.append(f"```diff\n{th.hunk.content}\n```\n")

    if blast_radius and blast_radius.impacted_symbols:
        parts.append("## Blast Radius Context")
        for impact in blast_radius.impacted_symbols[:10]:
            parts.append(
                f"- [{impact.risk_level.upper()}] {impact.symbol.kind} "
                f"'{impact.symbol.name}' in {impact.file_path}: {impact.reason}"
            )
        if blast_radius.security_boundaries:
            parts.append("\n### Security Boundaries Affected:")
            for boundary in blast_radius.security_boundaries[:5]:
                parts.append(f"- {boundary.boundary_type}: {boundary.description}")
        parts.append("")

    if rag_context:
        parts.append("## Similar Past Findings (for reference)")
        for ctx in rag_context[:5]:
            parts.append(
                f"- [{ctx['severity']}] {ctx['title']} in {ctx['file_path']}: {ctx['body'][:200]}"
            )
        parts.append("")

    return "\n".join(parts)


def _parse_ai_response(response_text: str) -> list[AIReviewFinding]:
    try:
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start == -1 or end == 0:
            return []
        json_str = response_text[start:end]
        items = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        logger.warning("ai_response_parse_error", response=response_text[:200])
        return []

    findings = []
    for item in items:
        try:
            findings.append(
                AIReviewFinding(
                    severity=item.get("severity", "INFO"),
                    category=item.get("category", "maintainability"),
                    file_path=item.get("file_path", ""),
                    line_start=item.get("line_start", 0),
                    line_end=item.get("line_end", 0),
                    title=item.get("title", ""),
                    body=item.get("body", ""),
                    suggestion=item.get("suggestion", ""),
                    evidence=item.get("evidence", ""),
                )
            )
        except Exception:
            logger.warning("finding_parse_error", item=item)

    return findings


async def review_chunk(
    chunk: list[TokenizedHunk],
    blast_radius: BlastRadiusReport | None = None,
    rag_context: list[dict] | None = None,
) -> tuple[list[AIReviewFinding], int]:
    """Send a chunk of diff hunks to the LLM for review."""
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_prompt = _build_chunk_prompt(chunk, blast_radius, rag_context)

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=settings.openai_max_tokens,
        response_format={"type": "json_object"},
    )

    content = response.choices[0].message.content or "[]"
    tokens_used = response.usage.total_tokens if response.usage else 0
    findings = _parse_ai_response(content)

    return findings, tokens_used


async def run_review(
    chunked_diff: ChunkedDiff,
    policy_result: PolicyEvaluationResult,
    blast_radius: BlastRadiusReport | None = None,
    rag_context: list[dict] | None = None,
) -> ReviewResult:
    """Execute the full AI review across all chunks."""
    result = ReviewResult(policy_violations=policy_result.violations)

    for chunk in chunked_diff.chunks:
        try:
            findings, tokens = await review_chunk(chunk, blast_radius, rag_context)
            result.findings.extend(findings)
            result.total_tokens_used += tokens
            result.chunks_processed += 1
        except Exception:
            logger.exception("chunk_review_failed", chunk_size=len(chunk))

    logger.info(
        "review_completed",
        findings=len(result.findings),
        policy_violations=len(result.policy_violations),
        tokens_used=result.total_tokens_used,
        chunks=result.chunks_processed,
    )

    return result
