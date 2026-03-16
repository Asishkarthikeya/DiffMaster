"""Policy Engine - evaluate code changes against org/repo-level policy rules."""

import fnmatch
import re
from dataclasses import dataclass, field

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import Policy, PolicyRule
from app.services.diff_parser import TokenizedHunk

logger = structlog.get_logger()


@dataclass
class PolicyViolation:
    rule_name: str
    rule_type: str
    severity: str
    file_path: str
    line: int
    message: str
    evidence: str
    suggestion: str = ""


@dataclass
class PolicyEvaluationResult:
    violations: list[PolicyViolation] = field(default_factory=list)
    rules_evaluated: int = 0
    rules_matched: int = 0

    @property
    def blocker_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "BLOCKER")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "WARNING")


SECRET_PATTERNS = [
    (r"(?i)(api[_-]?key|apikey)\s*[=:]\s*['\"][a-zA-Z0-9]{16,}", "Potential API key exposure"),
    (r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]+['\"]", "Hardcoded password detected"),
    (r"(?i)(secret|token)\s*[=:]\s*['\"][a-zA-Z0-9]{8,}", "Hardcoded secret/token"),
    (r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----", "Private key in source code"),
    (r"(?i)aws[_-]?(access[_-]?key|secret)", "AWS credential pattern"),
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token"),
    (r"sk-[a-zA-Z0-9]{20,}", "Potential API secret key"),
]

FORBIDDEN_API_DEFAULTS = [
    (r"\beval\s*\(", "Use of eval() is forbidden — risk of code injection"),
    (r"\bexec\s*\(", "Use of exec() is forbidden — risk of code injection"),
    (r"os\.system\s*\(", "Use of os.system() — prefer subprocess with shell=False"),
    (r"shell\s*=\s*True", "subprocess with shell=True — risk of shell injection"),
    (r"innerHTML\s*=", "Direct innerHTML assignment — XSS risk"),
    (r"dangerouslySetInnerHTML", "dangerouslySetInnerHTML usage — XSS risk"),
    (r"pickle\.loads?\s*\(", "pickle deserialization — risk of arbitrary code execution"),
    (r"yaml\.load\s*\((?!.*Loader)", "yaml.load without SafeLoader — unsafe deserialization"),
]


def _apply_regex_rule(
    rule: PolicyRule,
    hunk: TokenizedHunk,
) -> list[PolicyViolation]:
    violations = []
    pattern = re.compile(rule.pattern)

    for i, line in enumerate(hunk.added_lines):
        match = pattern.search(line)
        if match:
            violations.append(
                PolicyViolation(
                    rule_name=rule.name,
                    rule_type=rule.rule_type,
                    severity=rule.severity,
                    file_path=hunk.hunk.file_path,
                    line=hunk.hunk.new_start + i,
                    message=rule.message,
                    evidence=line.strip(),
                )
            )

    return violations


def _apply_builtin_secret_detection(hunk: TokenizedHunk) -> list[PolicyViolation]:
    violations = []
    for i, line in enumerate(hunk.added_lines):
        for pattern, message in SECRET_PATTERNS:
            if re.search(pattern, line):
                violations.append(
                    PolicyViolation(
                        rule_name="builtin_secret_detection",
                        rule_type="secret_detection",
                        severity="BLOCKER",
                        file_path=hunk.hunk.file_path,
                        line=hunk.hunk.new_start + i,
                        message=message,
                        evidence=(
                            line.strip()[:100] + "..."
                            if len(line) > 100
                            else line.strip()
                        ),
                        suggestion=(
                            "Remove the hardcoded secret and use "
                            "environment variables or a secrets manager."
                        ),
                    )
                )
                break
    return violations


def _apply_builtin_forbidden_apis(hunk: TokenizedHunk) -> list[PolicyViolation]:
    violations = []
    for i, line in enumerate(hunk.added_lines):
        for pattern, message in FORBIDDEN_API_DEFAULTS:
            if re.search(pattern, line):
                violations.append(
                    PolicyViolation(
                        rule_name="builtin_forbidden_api",
                        rule_type="forbidden_api",
                        severity="WARNING",
                        file_path=hunk.hunk.file_path,
                        line=hunk.hunk.new_start + i,
                        message=message,
                        evidence=line.strip(),
                    )
                )
    return violations


def _file_matches_glob(file_path: str, file_glob: str | None) -> bool:
    if not file_glob:
        return True
    return fnmatch.fnmatch(file_path, file_glob)


async def evaluate_policies(
    hunks: list[TokenizedHunk],
    session: AsyncSession,
    repo_policy_pack_id: str | None = None,
) -> PolicyEvaluationResult:
    """Evaluate all hunks against active policies and built-in rules."""
    result = PolicyEvaluationResult()

    for hunk in hunks:
        result.violations.extend(_apply_builtin_secret_detection(hunk))
        result.violations.extend(_apply_builtin_forbidden_apis(hunk))
        result.rules_evaluated += 2

    stmt = select(Policy).where(Policy.is_active.is_(True))
    db_result = await session.execute(stmt)
    policies = list(db_result.scalars().all())

    for policy in policies:
        for rule in policy.rules:
            if not rule.is_active:
                continue
            result.rules_evaluated += 1
            for hunk in hunks:
                if not _file_matches_glob(hunk.hunk.file_path, rule.file_glob):
                    continue
                violations = _apply_regex_rule(rule, hunk)
                if violations:
                    result.rules_matched += 1
                    result.violations.extend(violations)

    return result
