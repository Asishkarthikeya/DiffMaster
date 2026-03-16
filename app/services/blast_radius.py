"""Blast Radius Analysis - identify impacted call sites, dependencies, and security boundaries."""

from dataclasses import dataclass, field

import structlog

from app.integrations.base import VCSIntegration
from app.parsing.tree_sitter_parser import (
    CodeSymbol,
    FileAnalysis,
    analyze_file,
    find_modified_symbols,
)
from app.services.diff_parser import TokenizedHunk

logger = structlog.get_logger()


@dataclass
class ImpactedSymbol:
    symbol: CodeSymbol
    file_path: str
    risk_level: str  # high, medium, low
    reason: str


@dataclass
class SecurityBoundary:
    file_path: str
    boundary_type: str  # auth, input_validation, data_access, crypto
    line: int
    description: str


@dataclass
class BlastRadiusReport:
    impacted_symbols: list[ImpactedSymbol] = field(default_factory=list)
    security_boundaries: list[SecurityBoundary] = field(default_factory=list)
    total_impact_score: float = 0.0
    files_in_blast_radius: int = 0
    critical_paths_affected: bool = False


SECURITY_PATTERNS = {
    "auth": ["authenticate", "authorize", "login", "logout", "permission", "rbac", "acl"],
    "input_validation": ["validate", "sanitize", "escape", "clean", "filter_input"],
    "data_access": ["query", "execute", "cursor", "session", "transaction", "commit"],
    "crypto": ["encrypt", "decrypt", "hash", "sign", "verify", "hmac", "jwt", "token"],
}


def _detect_security_boundaries(
    analysis: FileAnalysis,
) -> list[SecurityBoundary]:
    boundaries = []
    for symbol in analysis.symbols:
        name_lower = symbol.name.lower()
        for boundary_type, patterns in SECURITY_PATTERNS.items():
            if any(p in name_lower for p in patterns):
                boundaries.append(
                    SecurityBoundary(
                        file_path=symbol.file_path,
                        boundary_type=boundary_type,
                        line=symbol.start_line,
                        description=f"{symbol.kind} '{symbol.name}' is a {boundary_type} boundary",
                    )
                )
                break
    return boundaries


def _classify_impact_risk(symbol: CodeSymbol, is_security: bool) -> str:
    if is_security:
        return "high"
    if symbol.kind == "class":
        return "medium"
    lines = symbol.end_line - symbol.start_line
    if lines > 50:
        return "medium"
    return "low"


async def analyze_blast_radius(
    tokenized_hunks: list[TokenizedHunk],
    vcs: VCSIntegration,
    repo_full_name: str,
    head_ref: str,
) -> BlastRadiusReport:
    """Perform blast radius analysis on modified hunks."""
    report = BlastRadiusReport()
    analyzed_files: dict[str, FileAnalysis] = {}
    all_security_names: set[str] = set()

    files_to_analyze = {th.hunk.file_path for th in tokenized_hunks}

    for file_path in files_to_analyze:
        try:
            file_content = await vcs.get_file_content(repo_full_name, file_path, head_ref)
            analysis = analyze_file(file_content.content, file_path)
            analyzed_files[file_path] = analysis

            boundaries = _detect_security_boundaries(analysis)
            report.security_boundaries.extend(boundaries)
            all_security_names.update(
                b.description.split("'")[1]
                for b in boundaries
                if "'" in b.description
            )
        except Exception:
            logger.warning("blast_radius_file_fetch_failed", file=file_path)

    for th in tokenized_hunks:
        analysis = analyzed_files.get(th.hunk.file_path)
        if not analysis:
            continue

        modified_lines = set()
        for i, line in enumerate(th.hunk.content.splitlines()):
            if line.startswith("+") and not line.startswith("+++"):
                modified_lines.add(th.hunk.new_start + i)
            elif line.startswith("-") and not line.startswith("---"):
                modified_lines.add(th.hunk.old_start + i)

        modified_symbols = find_modified_symbols(analysis, modified_lines)
        for sym in modified_symbols:
            is_security = sym.name in all_security_names
            risk = _classify_impact_risk(sym, is_security)
            report.impacted_symbols.append(
                ImpactedSymbol(
                    symbol=sym,
                    file_path=th.hunk.file_path,
                    risk_level=risk,
                    reason=(
                        f"Modified {sym.kind} '{sym.name}' "
                        f"({sym.end_line - sym.start_line} lines)"
                    ),
                )
            )
            if is_security:
                report.critical_paths_affected = True

    report.files_in_blast_radius = len(analyzed_files)

    high_count = sum(1 for s in report.impacted_symbols if s.risk_level == "high")
    medium_count = sum(1 for s in report.impacted_symbols if s.risk_level == "medium")
    report.total_impact_score = min(
        (high_count * 0.4 + medium_count * 0.2 + len(report.security_boundaries) * 0.15),
        1.0,
    )

    return report
