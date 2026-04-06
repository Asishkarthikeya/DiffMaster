"""
Celery tasks for async PR/MR review execution.

Tasks:
- run_review_task: Dispatches a GitHub or GitLab review
- enforce_retention_task: Periodic data retention cleanup (run via Celery Beat)
"""

import asyncio
import logging
import os
import sys
import time
from typing import Optional

# Ensure project root is on sys.path so `from main import run_review` works
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

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
    comment_body: str = "",
    comment_id: str = "",
):
    """
    Async Celery task: run DiffMaster review for a GitHub PR or GitLab MR.

    Args:
        vcs: "github" or "gitlab"
        repo: Repository full name (e.g. "org/repo")
        pr_number: Pull Request / Merge Request number
        head_sha: Head commit SHA
        gitlab_project_id: GitLab project ID (optional, for GitLab reviews)
        comment_body: Extracted query for ChatOps
        comment_id: For responding to existing comments
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
            comments = _run_github_review(repo, pr_number, head_sha, comment_body, comment_id)
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

def _run_github_review(repo: str, pr_number: int, head_sha: str, comment_body: str = "", comment_id: str = "") -> list:
    """Execute GitHub review pipeline synchronously in a new event loop."""
    import os

    # Load .env file so API keys are available in Celery workers
    _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    _env_path = os.path.join(_project_root, ".env")
    if os.path.exists(_env_path):
        with open(_env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    os.environ.setdefault(key.strip(), value.strip())

    os.environ["GITHUB_REPOSITORY"] = repo
    os.environ["PR_NUMBER"] = str(pr_number)
    os.environ["PR_COMMENT_BODY"] = comment_body
    os.environ["PR_COMMENT_ID"] = comment_id

    # Reload config so it picks up the env vars we just set
    import app.core.config as cfg
    cfg.settings = cfg.Settings()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        import importlib.util
        # Load main.py directly by absolute path — works regardless of sys.path
        _main_path = os.path.join(_project_root, "main.py")
        spec = importlib.util.spec_from_file_location("main", _main_path)
        main_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(main_module)
        loop.run_until_complete(main_module.run_review())
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
