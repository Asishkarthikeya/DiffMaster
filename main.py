"""
DiffMaster — GitHub Action Entrypoint (Full Spec)

Core Workflow:
1. Webhook Intake: GitHub Action triggers on PR events
2. Diff & Context Fetch: Retrieve hunks, file contents, repo metadata
3. Blast Radius Analysis: Tree-Sitter AST + NetworkX dependency graph
4. Vector RAG: FAISS in-memory index for codebase search
5. Policy-Aware Review: LangGraph multi-agent with policy packs
6. Comment Generation: Line-anchored, severity-tagged, explainable
7. Feedback Loop: Track previous comment resolution
8. Noise Control: Dedup, cap, severity filter
"""

import asyncio
import json
import fnmatch
import logging
import sys

from app.core.config import settings
from app.services.audit import get_audit_logger
from app.services.github_client import GitHubClient
from app.services.parser import parse_diff_hunks, get_modified_functions
from app.services.graph_builder import build_dependency_graph, get_blast_radius_context
from app.services.rag import build_codebase_index
from app.services.policy import load_policy_from_repo
from app.services.feedback import get_feedback_context
from app.services.agent_tools import create_tools
from app.services.orchestrator import build_review_graph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("diffmaster")

SEVERITY_RANK = {"BLOCKER": 3, "WARNING": 2, "INFO": 1}


def should_skip_file(filename: str, ignore_paths: list[str]) -> bool:
    """Check if file matches any ignore pattern."""
    for pattern in ignore_paths:
        if fnmatch.fnmatch(filename, pattern):
            return True
    # Skip binary and non-code files
    skip_extensions = (".lock", ".bin", ".png", ".jpg", ".svg", ".ico", ".woff", ".ttf")
    if filename.endswith(skip_extensions):
        return True
    return False


def deduplicate_comments(comments: list[dict]) -> list[dict]:
    """FR-1: Deduplicate comments with the same root cause."""
    seen = set()
    deduped = []
    for c in comments:
        # Key on file + severity + first 50 chars of body (root cause dedup)
        key = (c.get("file_path", ""), c.get("severity", ""), c.get("body", "")[:50])
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


async def run_review():
    """Main review pipeline."""
    repo = settings.GITHUB_REPOSITORY
    pr_number = int(settings.PR_NUMBER)

    # --- Startup validation ---
    logger.info("=" * 60)
    logger.info("🤖 DiffMaster AI Code Review")
    logger.info("=" * 60)
    logger.info(f"  Repository:    {repo}")
    logger.info(f"  PR Number:     {pr_number}")
    logger.info(f"  Gemini Key:    {'✅ Set' if settings.GEMINI_API_KEY else '❌ MISSING'}")
    logger.info(f"  Groq Key:      {'✅ Set' if settings.GROQ_API_KEY else '⚠️ Not set (optional)'}")
    logger.info(f"  GitHub Token:  {'✅ Set' if settings.GITHUB_TOKEN else '❌ MISSING'}")
    logger.info("=" * 60)

    if not repo or pr_number == 0:
        logger.error("GITHUB_REPOSITORY or PR_NUMBER not set.")
        sys.exit(1)

    if not settings.GEMINI_API_KEY and not settings.GROQ_API_KEY:
        logger.error("No LLM API keys set! Add GEMINI_API_KEY or GROQ_API_KEY as GitHub Secrets.")
        sys.exit(1)

    logger.info(f"🤖 DiffMaster reviewing {repo} PR #{pr_number}")

    # --- Initialize ---
    gh = GitHubClient()
    pr = gh.get_pull_request(repo, pr_number)
    head_sha = pr.head.sha

    # Check for ChatOps commands
    import os
    comment_body = os.environ.get("PR_COMMENT_BODY", "")
    comment_id = os.environ.get("PR_COMMENT_ID", "")

    if comment_body and "/ask" in comment_body.lower():
        logger.info(f"💬 ChatOps triggered: {comment_body}")
        pr_files = list(gh.get_pr_files(repo, pr_number))
        all_patches = "\n".join([f"File: {f.filename}\n{f.patch}" for f in pr_files if getattr(f, 'patch', None)])
        
        from app.services.llm import invoke_with_waterfall
        from langchain_core.messages import HumanMessage
        prompt = f"""You are DiffMaster, an AI Code Reviewer.
A developer asked a question about this Pull Request: \"{comment_body}\"

Here are the code changes in the PR:
{all_patches[:8000]}

Please answer the developer's question directly and concisely."""
        
        reply = invoke_with_waterfall([HumanMessage(content=prompt)], temperature=0.3)
        if reply:
            gh.reply_to_comment(repo, pr_number, reply)
        return

    # Step 4: Load Policy Pack (.diffmaster.yml)
    policy = load_policy_from_repo(gh, repo, ref=head_sha)
    min_severity = SEVERITY_RANK.get(policy.severity_filter.upper(), 1)
    logger.info(f"📋 Policy loaded. Max comments: {policy.max_comments}, severity filter: {policy.severity_filter}")

    # Step 6: Feedback Loop — check previous DiffMaster comments
    feedback = get_feedback_context(gh, repo, pr_number)
    logger.info(f"🔄 {feedback['summary']}")

    # Step 3 (partial): Build FAISS codebase index for RAG
    logger.info("🔍 Building codebase index (FAISS)...")
    rag_index = build_codebase_index(gh, repo, ref=head_sha, max_files=30)
    logger.info(f"🔍 Indexed {rag_index.size} code chunks")

    # Create LangChain tools with bound context
    tools = create_tools(rag_index, policy)

    # Build LangGraph review pipeline
    review_graph = build_review_graph(tools)

    # --- Process each file ---
    pr_files = list(gh.get_pr_files(repo, pr_number))
    all_comments = []

    for file in pr_files:
        if file.status not in ("modified", "added"):
            continue
        if not file.patch:
            continue
        if should_skip_file(file.filename, policy.ignore_paths):
            logger.debug(f"  ⏭️ Skipping {file.filename} (ignored by policy)")
            continue

        logger.info(f"  📄 Analyzing {file.filename}...")

        # Step 2: Parse diff hunks
        hunks = parse_diff_hunks(file.patch)
        if not hunks:
            continue

        all_added_lines = [line for hunk in hunks for line in hunk]

        # Step 2: Fetch raw file content
        raw_content = gh.get_file_content(repo, file.filename, ref=head_sha)

        # Step 3: Tree-Sitter AST → extract modified functions
        modified_functions = []
        if raw_content:
            modified_functions = get_modified_functions(raw_content, file.filename, all_added_lines)

        # Step 3: NetworkX blast radius
        graph = build_dependency_graph(modified_functions)
        modified_names = [f["node_name"] for f in modified_functions if f["node_name"] != "unknown"]
        blast_context = get_blast_radius_context(graph, modified_names)

        # Step 5: LangGraph multi-agent review
        hunks_str = json.dumps(all_added_lines, indent=2)

        initial_state = {
            "diff_hunks": hunks_str,
            "blast_radius_context": blast_context,
            "policy_rules": policy.format_for_llm(),
            "feedback_context": feedback["summary"],
            "messages": [],
            "proposed_comments": [],
            "grader_feedback": "",
            "iteration": 0,
        }

        try:
            final_state = await review_graph.ainvoke(initial_state)
            file_comments = final_state.get("proposed_comments", [])

            # Ensure file_path is set correctly
            for c in file_comments:
                c["file_path"] = file.filename

            all_comments.extend(file_comments)
        except Exception as e:
            logger.error(f"  ❌ LangGraph pipeline failed for {file.filename}: {e}")
            # Fallback: use simple LLM analysis
            from app.services.llm import analyze_diff
            fallback_comments = analyze_diff(hunks_str, blast_context)
            for c in fallback_comments:
                c["file_path"] = file.filename
            all_comments.extend(fallback_comments)

    # --- Post-processing ---
    # FR-1: Noise Control
    all_comments = deduplicate_comments(all_comments)

    # Filter by severity
    all_comments = [
        c for c in all_comments
        if SEVERITY_RANK.get(c.get("severity", "INFO"), 1) >= min_severity
    ]

    # Cap total comments
    all_comments = all_comments[:policy.max_comments]

    # Step 5: Post comments to GitHub
    if all_comments:
        logger.info(f"💬 Posting {len(all_comments)} inline review comments...")
        gh.post_review_comments(repo, pr_number, head_sha, all_comments)
        
        logger.info("📝 Synthesizing top-level PR summary...")
        from app.services.llm import generate_pr_summary, generate_pr_description
        summary_md = generate_pr_summary(all_comments)
        gh.post_pr_summary(repo, pr_number, summary_md)
        
        logger.info("📄 Generating automated PR description...")
        all_patches = "\n".join([f"File: {f.filename}\n{f.patch}" for f in pr_files if getattr(f, 'patch', None)])
        if all_patches:
            pr_desc = generate_pr_description(all_patches)
            gh.update_pr_description(repo, pr_number, pr_desc)
    else:
        logger.info("✅ No issues found. Clean PR!")

    logger.info("🤖 DiffMaster review complete.")

    # FR-4: Audit log the completed review
    audit = get_audit_logger()
    audit.log_event("review_completed", {
        "vcs": "github",
        "repo": repo,
        "pr_number": pr_number,
        "comments_posted": len(all_comments),
        "severity_filter": settings.SEVERITY_FILTER,
    })


def main():
    asyncio.run(run_review())


if __name__ == "__main__":
    main()
