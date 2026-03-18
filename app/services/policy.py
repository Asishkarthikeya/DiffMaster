"""
Policy Packs — reads `.diffmaster.yml` from the repo root.
Supports repo-level rules for security, performance, style, and noise control.
"""

import yaml
import logging

logger = logging.getLogger(__name__)

DEFAULT_POLICY = {
    "max_comments_per_pr": 15,
    "severity_filter": "INFO",
    "ignore_paths": ["*.lock", "*.min.js", "*.generated.*", "migrations/*"],
    "security": {
        "forbidden_apis": ["eval(", "exec(", "os.system(", "__import__(", "pickle.loads("],
        "require_parameterized_queries": True,
        "flag_hardcoded_secrets": True,
    },
    "performance": {
        "flag_n_plus_one": True,
        "require_timeouts_on_network_calls": True,
        "flag_unbounded_loops": True,
    },
    "style": {
        "require_docstrings": True,
        "naming_convention": "snake_case",
        "flag_dead_code": True,
    },
}


class PolicyPack:
    """Repo-level policy configuration."""

    def __init__(self, config: dict = None):
        self.config = {**DEFAULT_POLICY, **(config or {})}

    @property
    def max_comments(self) -> int:
        return self.config.get("max_comments_per_pr", 15)

    @property
    def severity_filter(self) -> str:
        return self.config.get("severity_filter", "INFO")

    @property
    def ignore_paths(self) -> list[str]:
        return self.config.get("ignore_paths", [])

    @property
    def security_rules(self) -> dict:
        return self.config.get("security", {})

    @property
    def performance_rules(self) -> dict:
        return self.config.get("performance", {})

    @property
    def style_rules(self) -> dict:
        return self.config.get("style", {})

    def format_for_llm(self) -> str:
        """Format policy rules as a string for the LLM system prompt."""
        parts = []

        sec = self.security_rules
        if sec.get("forbidden_apis"):
            parts.append(f"FORBIDDEN APIs (flag as BLOCKER): {', '.join(sec['forbidden_apis'])}")
        if sec.get("require_parameterized_queries"):
            parts.append("All SQL queries MUST use parameterized execution (no string formatting).")
        if sec.get("flag_hardcoded_secrets"):
            parts.append("Flag any hardcoded API keys, passwords, tokens, or secrets as BLOCKER.")

        perf = self.performance_rules
        if perf.get("flag_n_plus_one"):
            parts.append("Flag N+1 query patterns (DB calls inside loops) as WARNING.")
        if perf.get("require_timeouts_on_network_calls"):
            parts.append("All HTTP/network calls MUST have explicit timeouts.")
        if perf.get("flag_unbounded_loops"):
            parts.append("Flag unbounded loops without exit conditions as WARNING.")

        style = self.style_rules
        if style.get("require_docstrings"):
            parts.append("All public functions should have docstrings (INFO severity).")
        if style.get("flag_dead_code"):
            parts.append("Flag unreachable/dead code as INFO.")

        return "\n".join(f"- {p}" for p in parts) if parts else "No specific policy rules configured."


def load_policy_from_repo(gh_client, repo_name: str, ref: str) -> PolicyPack:
    """Load `.diffmaster.yml` from the repo. Falls back to defaults."""
    try:
        content = gh_client.get_file_content(repo_name, ".diffmaster.yml", ref=ref)
        if content:
            config = yaml.safe_load(content)
            logger.info(f"Loaded policy pack from {repo_name}/.diffmaster.yml")
            return PolicyPack(config)
    except Exception as e:
        logger.debug(f"No .diffmaster.yml found: {e}")

    logger.info("Using default policy pack.")
    return PolicyPack()
