"""
Feedback Loop — tracks which DiffMaster comments were accepted/rejected.
Uses the GitHub API to check previous review comments on the PR.
"""

import logging

logger = logging.getLogger(__name__)


def get_feedback_context(gh_client, repo_name: str, pr_number: int) -> dict:
    """
    Fetch previous DiffMaster comments on this PR and check their status.
    Returns stats + context to help the LLM reduce noise on re-runs.
    """
    stats = {
        "total_previous": 0,
        "resolved": 0,
        "dismissed": 0,
        "open": 0,
        "previously_flagged_files": set(),
        "summary": "",
    }

    try:
        pr = gh_client.get_pull_request(repo_name, pr_number)
        reviews = pr.get_reviews()
        review_comments = pr.get_review_comments()

        for comment in review_comments:
            # Only look at DiffMaster's own comments
            body = comment.body or ""
            if "DiffMaster Review" not in body:
                continue

            stats["total_previous"] += 1
            stats["previously_flagged_files"].add(comment.path)

            # Check if the comment thread was resolved
            # PyGithub doesn't directly expose "resolved" status on individual comments,
            # but we can check if the comment was part of a resolved review thread
            if hasattr(comment, 'in_reply_to_id') and comment.in_reply_to_id:
                stats["resolved"] += 1
            else:
                stats["open"] += 1

        # Build a summary for the LLM
        if stats["total_previous"] > 0:
            stats["summary"] = (
                f"FEEDBACK CONTEXT: DiffMaster previously posted {stats['total_previous']} comments on this PR. "
                f"{stats['resolved']} were resolved by the developer (accepted), "
                f"{stats['open']} are still open. "
                f"Previously flagged files: {', '.join(stats['previously_flagged_files'])}. "
                f"Avoid re-posting the same issues on unchanged lines."
            )
            stats["previously_flagged_files"] = list(stats["previously_flagged_files"])
        else:
            stats["summary"] = "This is the first DiffMaster review on this PR."

    except Exception as e:
        logger.debug(f"Could not fetch feedback context: {e}")
        stats["summary"] = "No previous feedback data available."

    logger.info(f"Feedback: {stats['total_previous']} previous comments, {stats['resolved']} resolved")
    return stats
