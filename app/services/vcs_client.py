"""
VCS-Agnostic Review Pipeline

Provides run_vcs_review() — the same core review logic that works with
any VCS client (GitHubClient or GitLabClient) that implements the interface:
  - get_pr_files(repo, pr_number)
  - get_file_content(repo, file_path, ref)
  - post_review_comments(repo, pr_number, commit_sha, comments)

The GitHub Action entrypoint (main.py) uses GitHubClient directly.
The FastAPI server (app/workers/review_tasks.py) calls run_vcs_review()
for both GitHub and GitLab workflows.
"""

import fnmatch
import json
import logging
from typing import Any

logger = logging.getLogger("diffmaster.vcs")

SEVERITY_RANK = {"BLOCKER": 3, "WARNING": 2, "INFO": 1}


def _should_skip_file(filename: str, ignore_paths: list[str]) -> bool:
    for pattern in ignore_paths:
        if fnmatch.fnmatch(filename, pattern):
            return True
    skip_extensions = (".lock", ".bin", ".png", ".jpg", ".jpeg", ".svg",
                       ".ico", ".woff", ".ttf", ".gif", ".webp")
    return filename.endswith(skip_extensions)


def _deduplicate_comments(comments: list[dict]) -> list[dict]:
    seen: set = set()
    deduped: list[dict] = []
    for c in comments:
        key = (c.get("file_path", ""), c.get("severity", ""), c.get("body", "")[:50])
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


async def run_vcs_review(
    vcs_client: Any,
    repo: str,
    pr_number: int,
    head_sha: str,
) -> list[dict]:
    """
    VCS-agnostic review pipeline.

    Accepts any client that implements the GitHubClient / GitLabClient interface.
    Returns the list of comments that were posted.

    Args:
        vcs_client: GitHubClient or GitLabClient instance
        repo: Repository full name (org/repo or namespace/project)
        pr_number: Pull Request / Merge Request number
        head_sha: Head commit SHA for the PR/MR

    Returns:
        List of comment dicts that were posted to the VCS.
    """
    from app.services.parser import parse_diff_hunks, get_modified_functions
    from app.services.graph_builder import build_dependency_graph, get_blast_radius_context
    from app.services.rag import build_codebase_index
    from app.services.policy import load_policy_from_repo
    from app.services.agent_tools import create_tools
    from app.services.orchestrator import build_review_graph
    from app.services.llm import analyze_diff

    # Load policy pack from .diffmaster.yml
    policy = load_policy_from_repo(vcs_client, repo, ref=head_sha)
    min_severity = SEVERITY_RANK.get(policy.severity_filter.upper(), 1)
    logger.info(f"Policy: max_comments={policy.max_comments}, filter={policy.severity_filter}")

    # Build FAISS codebase index for RAG
    logger.info("Building codebase index (FAISS)...")
    rag_index = build_codebase_index(vcs_client, repo, ref=head_sha, max_files=30)
    logger.info(f"Indexed {rag_index.size} code chunks")

    tools = create_tools(rag_index, policy)
    review_graph = build_review_graph(tools)

    pr_files = vcs_client.get_pr_files(repo, pr_number)
    all_comments: list[dict] = []

    for file in pr_files:
        if file.status not in ("modified", "added"):
            continue
        if not file.patch:
            continue
        if _should_skip_file(file.filename, policy.ignore_paths):
            logger.debug(f"Skipping {file.filename} (ignored by policy)")
            continue

        logger.info(f"Analyzing {file.filename}...")

        hunks = parse_diff_hunks(file.patch)
        if not hunks:
            continue

        all_added_lines = [line for hunk in hunks for line in hunk]
        raw_content = vcs_client.get_file_content(repo, file.filename, ref=head_sha)

        modified_functions = []
        if raw_content:
            modified_functions = get_modified_functions(
                raw_content, file.filename, all_added_lines
            )

        graph = build_dependency_graph(modified_functions)
        modified_names = [
            f["node_name"] for f in modified_functions if f["node_name"] != "unknown"
        ]
        blast_context = get_blast_radius_context(graph, modified_names)
        hunks_str = json.dumps(all_added_lines, indent=2)

        initial_state = {
            "diff_hunks": hunks_str,
            "blast_radius_context": blast_context,
            "policy_rules": policy.format_for_llm(),
            "feedback_context": "",
            "messages": [],
            "proposed_comments": [],
            "grader_feedback": "",
            "iteration": 0,
        }

        try:
            final_state = await review_graph.ainvoke(initial_state)
            file_comments = final_state.get("proposed_comments", [])
            for c in file_comments:
                c["file_path"] = file.filename
            all_comments.extend(file_comments)
        except Exception as e:
            logger.error(f"LangGraph pipeline failed for {file.filename}: {e}")
            fallback_comments = analyze_diff(hunks_str, blast_context)
            for c in fallback_comments:
                c["file_path"] = file.filename
            all_comments.extend(fallback_comments)

    # Post-processing: dedup, filter by severity, cap
    all_comments = _deduplicate_comments(all_comments)
    all_comments = [
        c for c in all_comments
        if SEVERITY_RANK.get(c.get("severity", "INFO"), 1) >= min_severity
    ]
    all_comments = all_comments[: policy.max_comments]

    if all_comments:
        logger.info(f"Posting {len(all_comments)} review comments...")
        vcs_client.post_review_comments(repo, pr_number, head_sha, all_comments)
    else:
        logger.info("No issues found. Clean PR!")

    return all_comments
