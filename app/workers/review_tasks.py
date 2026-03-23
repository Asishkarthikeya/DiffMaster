"""
Celery tasks for async PR/MR review execution.

Tasks:
- run_review_task: Dispatches a GitHub or GitLab review
- enforce_retention_task: Periodic data retention cleanup (run via Celery Beat)
"""

import asyncio
import logging
import time
from typing import Optional

from celery import Task
from app.workers.celery_app import celery_app
from app.services.audit import get_audit_logger

logger = logging.getLogger("diffmaster.tasks")


class ReviewTask(Task):
    """Base task with audit logging on success/failure."""
    abstract = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        get_audit_logger().log_event("review_task_failed", {
            "task_id": task_id,
            "error": str(exc),
            "vcs": kwargs.get("vcs"),
            "repo": kwargs.get("repo"),
            "pr_number": kwargs.get("pr_number"),
        })

    def on_success(self, retval, task_id, args, kwargs):
        get_audit_logger().log_event("review_task_succeeded", {
            "task_id": task_id,
            "vcs": kwargs.get("vcs"),
            "repo": kwargs.get("repo"),
            "pr_number": kwargs.get("pr_number"),
            "comments_posted": retval.get("comments_posted", 0) if retval else 0,
        })


@celery_app.task(
    bind=True,
    base=ReviewTask,
    name="diffmaster.run_review",
    max_retries=3,
    default_retry_delay=30,
)
def run_review_task(
    self,
    vcs: str,
    repo: str,
    pr_number: int,
    head_sha: str,
    gitlab_project_id: Optional[int] = None,
):
    """
    Async Celery task: run DiffMaster review for a GitHub PR or GitLab MR.

    Args:
        vcs: "github" or "gitlab"
        repo: Repository full name (e.g. "org/repo")
        pr_number: Pull Request / Merge Request number
        head_sha: Head commit SHA
        gitlab_project_id: GitLab project ID (optional, for GitLab reviews)
    """
    task_id = self.request.id
    start_time = time.time()
    audit = get_audit_logger()

    logger.info(f"[Task {task_id}] Starting {vcs} review for {repo}#{pr_number}")
    audit.log_event("review_started", {
        "task_id": task_id,
        "vcs": vcs,
        "repo": repo,
        "pr_number": pr_number,
        "head_sha": head_sha,
    })

    try:
        if vcs == "github":
            comments = _run_github_review(repo, pr_number, head_sha)
        elif vcs == "gitlab":
            comments = _run_gitlab_review(repo, pr_number, head_sha, gitlab_project_id)
        elif vcs == "bitbucket":
            comments = _run_bitbucket_review(repo, pr_number, head_sha)
        else:
            raise ValueError(f"Unsupported VCS: {vcs}")

        duration_ms = int((time.time() - start_time) * 1000)
        result = {
            "status": "completed",
            "comments_posted": len(comments),
            "duration_ms": duration_ms,
        }

        audit.log_event("review_completed", {
            "task_id": task_id,
            "vcs": vcs,
            "repo": repo,
            "pr_number": pr_number,
            "comments_posted": len(comments),
            "duration_ms": duration_ms,
        })

        logger.info(f"[Task {task_id}] Completed in {duration_ms}ms — {len(comments)} comments")
        return result

    except Exception as exc:
        logger.error(f"[Task {task_id}] Review failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)


@celery_app.task(name="diffmaster.enforce_retention")
def enforce_retention_task():
    """
    Periodic retention cleanup task.
    Schedule via Celery Beat: celery_app.conf.beat_schedule
    """
    from app.services.retention import get_retention_policy
    policy = get_retention_policy()
    results = policy.run_all()
    logger.info(f"Retention task completed: {results}")
    return results


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _run_github_review(repo: str, pr_number: int, head_sha: str) -> list:
    """Execute GitHub review pipeline synchronously in a new event loop."""
    import os
    os.environ["GITHUB_REPOSITORY"] = repo
    os.environ["PR_NUMBER"] = str(pr_number)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from main import run_review
        loop.run_until_complete(run_review())
        return []  # main.py handles posting; return empty list for count
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _run_gitlab_review(
    repo: str, mr_iid: int, head_sha: str, project_id: Optional[int]
) -> list:
    """Execute GitLab MR review pipeline synchronously in a new event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from app.services.gitlab_client import GitLabClient
        from app.services.vcs_client import run_vcs_review

        gl_client = GitLabClient(default_project_id=project_id)
        comments = loop.run_until_complete(
            run_vcs_review(
                vcs_client=gl_client,
                repo=repo,
                pr_number=mr_iid,
                head_sha=head_sha,
            )
        )
        return comments
    finally:
        loop.close()
        asyncio.set_event_loop(None)


def _run_bitbucket_review(repo: str, pr_number: int, head_sha: str) -> list:
    """Execute Bitbucket PR review pipeline synchronously in a new event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        from app.services.bitbucket_client import BitbucketClient
        from app.services.vcs_client import run_vcs_review

        bb_client = BitbucketClient()
        comments = loop.run_until_complete(
            run_vcs_review(
                vcs_client=bb_client,
                repo=repo,
                pr_number=pr_number,
                head_sha=head_sha,
            )
        )
        return comments
    finally:
        loop.close()
        asyncio.set_event_loop(None)
