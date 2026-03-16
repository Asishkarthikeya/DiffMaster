"""Webhook intake endpoints for GitHub and GitLab."""


import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.integrations.webhook_validator import (
    validate_github_signature,
    validate_gitlab_token,
)
from app.models.repository import Repository
from app.models.review import Review, ReviewStatus
from app.schemas.webhook import (
    GitHubWebhookPayload,
    GitLabWebhookPayload,
    WebhookResponse,
)
from app.workers.tasks import process_pr_review

logger = structlog.get_logger()
settings = get_settings()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

SUPPORTED_GITHUB_ACTIONS = {"opened", "synchronize", "reopened"}
SUPPORTED_GITLAB_ACTIONS = {"open", "update", "reopen"}


@router.post("/github", response_model=WebhookResponse)
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    session: AsyncSession = Depends(get_db),
):
    body = await request.body()

    if settings.github_webhook_secret and not validate_github_signature(
        body, x_hub_signature_256 or "", settings.github_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    if x_github_event != "pull_request":
        return WebhookResponse(status="ignored", message=f"Event '{x_github_event}' not handled")

    payload = GitHubWebhookPayload.model_validate_json(body)

    if payload.action not in SUPPORTED_GITHUB_ACTIONS:
        return WebhookResponse(
            status="ignored",
            message=f"Action '{payload.action}' not handled",
        )

    repo_full_name = payload.repository.full_name
    stmt = select(Repository).where(Repository.full_name == repo_full_name)
    result = await session.execute(stmt)
    repo = result.scalar_one_or_none()

    if not repo:
        repo = Repository(
            platform="github",
            owner=payload.repository.owner.login,
            name=payload.repository.name,
            full_name=repo_full_name,
            default_branch=payload.repository.default_branch,
            language=payload.repository.language,
        )
        session.add(repo)
        await session.flush()

    if not repo.webhook_active:
        return WebhookResponse(status="ignored", message="Webhook disabled for this repository")

    pr = payload.pull_request
    review = Review(
        repository_id=repo.id,
        pr_number=pr.number,
        pr_title=pr.title,
        pr_author=pr.user.login,
        head_sha=pr.head.sha,
        base_sha=pr.base.sha,
        status=ReviewStatus.PENDING,
    )
    session.add(review)
    await session.flush()

    task = process_pr_review.delay(str(review.id))
    review.celery_task_id = task.id
    await session.commit()

    logger.info(
        "review_queued",
        repo=repo_full_name,
        pr=pr.number,
        review_id=str(review.id),
    )

    return WebhookResponse(
        status="queued",
        review_id=str(review.id),
        message=f"Review queued for PR #{pr.number}",
    )


@router.post("/gitlab", response_model=WebhookResponse)
async def gitlab_webhook(
    request: Request,
    x_gitlab_token: str | None = Header(None, alias="X-Gitlab-Token"),
    session: AsyncSession = Depends(get_db),
):
    body = await request.body()

    if settings.gitlab_webhook_secret and not validate_gitlab_token(
        x_gitlab_token or "", settings.gitlab_webhook_secret
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    payload = GitLabWebhookPayload.model_validate_json(body)

    if payload.object_kind != "merge_request":
        return WebhookResponse(status="ignored", message="Not a merge request event")

    attrs = payload.object_attributes
    action = attrs.state
    if action not in SUPPORTED_GITLAB_ACTIONS:
        return WebhookResponse(status="ignored", message=f"State '{action}' not handled")

    repo_full_name = payload.project.path_with_namespace
    stmt = select(Repository).where(Repository.full_name == repo_full_name)
    result = await session.execute(stmt)
    repo = result.scalar_one_or_none()

    if not repo:
        repo = Repository(
            platform="gitlab",
            owner=repo_full_name.split("/")[0],
            name=payload.project.name,
            full_name=repo_full_name,
            default_branch=payload.project.default_branch,
        )
        session.add(repo)
        await session.flush()

    if not repo.webhook_active:
        return WebhookResponse(status="ignored", message="Webhook disabled for this repository")

    last_commit = attrs.last_commit
    review = Review(
        repository_id=repo.id,
        pr_number=attrs.iid,
        pr_title=attrs.title,
        pr_author=str(attrs.author_id),
        head_sha=last_commit.get("id", ""),
        base_sha="",
        status=ReviewStatus.PENDING,
    )
    session.add(review)
    await session.flush()

    task = process_pr_review.delay(str(review.id))
    review.celery_task_id = task.id
    await session.commit()

    return WebhookResponse(
        status="queued",
        review_id=str(review.id),
        message=f"Review queued for MR !{attrs.iid}",
    )
