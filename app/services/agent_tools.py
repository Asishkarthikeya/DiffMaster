"""
LangChain tools for the DiffMaster ReAct agent.
- code_search: queries FAISS index for similar code patterns
- check_policy: reads the repo's policy pack rules
"""

from langchain_core.tools import tool
import logging

logger = logging.getLogger(__name__)

# These get bound at runtime via create_tools()
_rag_index = None
_policy_pack = None


def create_tools(rag_index, policy_pack):
    """Create LangChain tools with bound context."""
    global _rag_index, _policy_pack
    _rag_index = rag_index
    _policy_pack = policy_pack

    @tool("code_search")
    def code_search(query: str) -> str:
        """
        Search the codebase for similar code patterns or architectural conventions.
        Use this when you need to understand how something is typically done in this repo,
        or to verify if a function/pattern exists elsewhere.
        Args:
            query: Semantic search query (e.g., "how is user authentication handled?")
        """
        if not _rag_index or _rag_index.size == 0:
            return "No codebase index available. Proceed with the information in the diff."

        results = _rag_index.search(query, top_k=3)
        if not results:
            return f"No similar code found for: {query}"

        formatted = []
        for r in results:
            formatted.append(
                f"File: {r['file_path']} | {r['node_type']} {r['node_name']} (score: {r['score']:.2f})\n"
                f"{r['content'][:500]}"
            )
        return "\n\n---\n\n".join(formatted)

    @tool("check_policy")
    def check_policy(category: str) -> str:
        """
        Check the repository's policy rules for a specific category.
        Use this to verify security, performance, or style standards before making a recommendation.
        Args:
            category: One of 'security', 'performance', 'style', or 'all'
        """
        if not _policy_pack:
            return "No policy pack configured for this repository."

        category = category.lower().strip()

        if category == "all":
            return _policy_pack.format_for_llm()
        elif category == "security":
            rules = _policy_pack.security_rules
            if rules.get("forbidden_apis"):
                return f"Forbidden APIs: {', '.join(rules['forbidden_apis'])}\nRequire parameterized queries: {rules.get('require_parameterized_queries', False)}\nFlag hardcoded secrets: {rules.get('flag_hardcoded_secrets', False)}"
            return "No specific security rules configured."
        elif category == "performance":
            rules = _policy_pack.performance_rules
            return f"Flag N+1: {rules.get('flag_n_plus_one', False)}\nRequire timeouts: {rules.get('require_timeouts_on_network_calls', False)}\nFlag unbounded loops: {rules.get('flag_unbounded_loops', False)}"
        elif category == "style":
            rules = _policy_pack.style_rules
            return f"Require docstrings: {rules.get('require_docstrings', False)}\nNaming: {rules.get('naming_convention', 'any')}\nFlag dead code: {rules.get('flag_dead_code', False)}"
        else:
            return f"Unknown policy category: {category}. Use 'security', 'performance', 'style', or 'all'."

    return [code_search, check_policy]
