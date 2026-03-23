"""
Webhook routes for GitHub, GitLab, and Bitbucket PR/MR events.

Handles:
- Signature / token validation (HMAC-SHA256 for GitHub, shared token for GitLab/Bitbucket)
- Per-repo rate limiting
- Dispatching async Celery review tasks
- Fallback to BackgroundTasks when Celery is unavailable
"""

import hashlib
import hmac
import json
import logging
import time
from collections import defaultdict
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, Response

from app.core.config import settings
from app.services.audit import get_audit_logger

router = APIRouter()
logger = logging.getLogger("diffmaster.webhooks")

# In-memory rate limit store: repo -> list of request timestamps
_rate_limit_store: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str) -> bool:
    """Return True if request is allowed, False if rate limited."""
    now = time.time()
    window = settings.RATE_LIMIT_WINDOW
    max_req = settings.RATE_LIMIT_REQUESTS

    # Evict expired timestamps
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < window]

    if len(_rate_limit_store[key]) >= max_req:
        return False

    _rate_limit_store[key].append(now)
    return True


def _verify_github_signature(payload: bytes, signature: Optional[str]) -> bool:
    """Validate GitHub HMAC-SHA256 webhook signature (X-Hub-Signature-256)."""
    if not settings.WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not set — skipping signature validation")
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(
        settings.WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _verify_gitlab_token(token: Optional[str]) -> bool:
    """Validate GitLab webhook secret token (X-Gitlab-Token)."""
    if not settings.WEBHOOK_SECRET:
        logger.warning("WEBHOOK_SECRET not set — skipping token validation")
        return True
    if not token:
        return False
    return hmac.compare_digest(settings.WEBHOOK_SECRET, token)


# ------------------------------------------------------------------
# GitHub webhook
# ------------------------------------------------------------------

@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
    x_github_delivery: Optional[str] = Header(None),
):
    """
    Handle GitHub pull_request webhook events.

    Triggers on: opened, synchronize, reopened
    Validates HMAC-SHA256 signature and rate-limits per repo.
    """
    audit = get_audit_logger()
    payload_bytes = await request.body()

    # 1. Validate signature
    if not _verify_github_signature(payload_bytes, x_hub_signature_256):
        audit.log_event("webhook_rejected", {
            "vcs": "github",
            "reason": "invalid_signature",
            "delivery_id": x_github_delivery,
        })
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # 2. Parse payload
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 3. Filter to pull_request events we care about
    if x_github_event != "pull_request":
        return Response(status_code=200, content="Event ignored")

    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        return Response(status_code=200, content="Action ignored")

    repo = payload.get("repository", {}).get("full_name", "")
    pr_number = payload.get("number")
    head_sha = payload.get("pull_request", {}).get("head", {}).get("sha", "")

    if not repo or not pr_number:
        raise HTTPException(status_code=400, detail="Missing repo or PR number in payload")

    # 4. Rate limit per repo
    if not _check_rate_limit(repo):
        audit.log_event("webhook_rate_limited", {
            "vcs": "github",
            "repo": repo,
            "pr_number": pr_number,
        })
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this repository")

    audit.log_event("review_queued", {
        "vcs": "github",
        "repo": repo,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "delivery_id": x_github_delivery,
    })

    # 5. Dispatch Celery task (fallback to BackgroundTask if Redis unavailable)
    try:
        from app.workers.review_tasks import run_review_task
        task = run_review_task.delay(
            vcs="github",
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
        )
        logger.info(f"Queued review for {repo}#{pr_number} — task_id={task.id}")
        return {"status": "queued", "task_id": task.id, "repo": repo, "pr": pr_number}
    except Exception as e:
        logger.warning(f"Celery unavailable ({e}), running in-process via BackgroundTasks")
        background_tasks.add_task(_run_sync_github_review, repo, pr_number)
        return {"status": "processing", "repo": repo, "pr": pr_number}


# ------------------------------------------------------------------
# GitLab webhook
# ------------------------------------------------------------------

@router.post("/gitlab")
async def gitlab_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_gitlab_token: Optional[str] = Header(None),
    x_gitlab_event: Optional[str] = Header(None),
):
    """
    Handle GitLab Merge Request webhook events.

    Triggers on: open, update, reopen
    Validates the X-Gitlab-Token secret header.
    """
    audit = get_audit_logger()
    payload_bytes = await request.body()

    # 1. Validate token
    if not _verify_gitlab_token(x_gitlab_token):
        audit.log_event("webhook_rejected", {
            "vcs": "gitlab",
            "reason": "invalid_token",
        })
        raise HTTPException(status_code=401, detail="Invalid GitLab webhook token")

    # 2. Parse payload
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 3. Filter to Merge Request events
    if x_gitlab_event != "Merge Request Hook":
        return Response(status_code=200, content="Event ignored")

    attrs = payload.get("object_attributes", {})
    action = attrs.get("action", "")
    if action not in ("open", "update", "reopen"):
        return Response(status_code=200, content="Action ignored")

    project = payload.get("project", {})
    repo = project.get("path_with_namespace", "")
    project_id = project.get("id")
    mr_iid = attrs.get("iid")
    head_sha = attrs.get("last_commit", {}).get("id", "")

    if not repo or not mr_iid:
        raise HTTPException(status_code=400, detail="Missing repo or MR IID in payload")

    # 4. Rate limit per repo
    if not _check_rate_limit(repo):
        audit.log_event("webhook_rate_limited", {
            "vcs": "gitlab",
            "repo": repo,
            "mr_iid": mr_iid,
        })
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this repository")

    audit.log_event("review_queued", {
        "vcs": "gitlab",
        "repo": repo,
        "project_id": project_id,
        "mr_iid": mr_iid,
        "head_sha": head_sha,
    })

    # 5. Dispatch Celery task
    try:
        from app.workers.review_tasks import run_review_task
        task = run_review_task.delay(
            vcs="gitlab",
            repo=repo,
            pr_number=mr_iid,
            head_sha=head_sha,
            gitlab_project_id=project_id,
        )
        logger.info(f"Queued GitLab review for {repo}!{mr_iid} — task_id={task.id}")
        return {"status": "queued", "task_id": task.id, "repo": repo, "mr": mr_iid}
    except Exception as e:
        logger.warning(f"Celery unavailable ({e}), cannot process GitLab review in-process")
        return {"status": "error", "detail": "Celery worker unavailable", "repo": repo}


# ------------------------------------------------------------------
# Bitbucket webhook
# ------------------------------------------------------------------

@router.post("/bitbucket")
async def bitbucket_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_event_key: Optional[str] = Header(None),
    x_hook_uuid: Optional[str] = Header(None),
):
    """
    Handle Bitbucket Cloud Pull Request webhook events.

    Triggers on: pullrequest:created, pullrequest:updated
    """
    audit = get_audit_logger()
    payload_bytes = await request.body()

    # 1. Parse payload
    try:
        payload = json.loads(payload_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 2. Filter to pull request events
    if x_event_key not in ("pullrequest:created", "pullrequest:updated"):
        return Response(status_code=200, content="Event ignored")

    pr_data = payload.get("pullrequest", {})
    repo_data = payload.get("repository", {})
    repo = repo_data.get("full_name", "")
    pr_number = pr_data.get("id")
    head_sha = pr_data.get("source", {}).get("commit", {}).get("hash", "")

    if not repo or not pr_number:
        raise HTTPException(status_code=400, detail="Missing repo or PR number in payload")

    # 3. Rate limit per repo
    if not _check_rate_limit(repo):
        audit.log_event("webhook_rate_limited", {
            "vcs": "bitbucket",
            "repo": repo,
            "pr_number": pr_number,
        })
        raise HTTPException(status_code=429, detail="Rate limit exceeded for this repository")

    audit.log_event("review_queued", {
        "vcs": "bitbucket",
        "repo": repo,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "hook_uuid": x_hook_uuid,
    })

    # 4. Dispatch Celery task
    try:
        from app.workers.review_tasks import run_review_task
        task = run_review_task.delay(
            vcs="bitbucket",
            repo=repo,
            pr_number=pr_number,
            head_sha=head_sha,
        )
        logger.info(f"Queued Bitbucket review for {repo}#{pr_number} — task_id={task.id}")
        return {"status": "queued", "task_id": task.id, "repo": repo, "pr": pr_number}
    except Exception as e:
        logger.warning(f"Celery unavailable ({e}), cannot process Bitbucket review in-process")
        return {"status": "error", "detail": "Celery worker unavailable", "repo": repo}


# ------------------------------------------------------------------
# Fallback: in-process sync review (no Celery)
# ------------------------------------------------------------------

async def _run_sync_github_review(repo: str, pr_number: int) -> None:
    """Run a GitHub review synchronously as a FastAPI BackgroundTask."""
    import os
    os.environ["GITHUB_REPOSITORY"] = repo
    os.environ["PR_NUMBER"] = str(pr_number)
    try:
        from main import run_review
        await run_review()
    except Exception as e:
        logger.error(f"Sync review failed for {repo}#{pr_number}: {e}")
