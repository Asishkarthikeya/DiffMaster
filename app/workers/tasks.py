"""Celery task definitions for async review processing."""

import asyncio
import time
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.integrations.base import ReviewCommentPayload
from app.integrations.github_integration import GitHubIntegration
from app.integrations.gitlab_integration import GitLabIntegration
from app.models.comment import ReviewComment
from app.models.repository import Repository
from app.models.review import Review, ReviewStatus
from app.services.blast_radius import analyze_blast_radius
from app.services.comment_generator import (
    format_for_vcs,
    generate_comments,
    generate_summary,
)
from app.services.diff_parser import smart_chunk, tokenize_hunks
from app.services.policy_engine import evaluate_policies
from app.services.review_engine import run_review
from app.workers.celery_app import celery_app

logger = structlog.get_logger()
settings = get_settings()


def _get_async_session() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


def _get_vcs(platform: str):
    if platform == "github":
        return GitHubIntegration()
    elif platform == "gitlab":
        return GitLabIntegration()
    raise ValueError(f"Unsupported platform: {platform}")


async def _process_review(review_id: str) -> None:
    session_factory = _get_async_session()

    async with session_factory() as session:
        stmt = select(Review).where(Review.id == review_id)
        result = await session.execute(stmt)
        review = result.scalar_one_or_none()
        if not review:
            logger.error("review_not_found", review_id=review_id)
            return

        repo_stmt = select(Repository).where(Repository.id == review.repository_id)
        repo_result = await session.execute(repo_stmt)
        repo = repo_result.scalar_one_or_none()
        if not repo:
            logger.error("repository_not_found", repo_id=str(review.repository_id))
            return

        review.status = ReviewStatus.PROCESSING
        review.started_at = datetime.now(UTC)
        await session.commit()

        start_time = time.monotonic()
        try:
            vcs = _get_vcs(repo.platform)

            diff_hunks = await vcs.get_diff(repo.full_name, review.pr_number)
            if not diff_hunks:
                review.status = ReviewStatus.COMPLETED
                review.completed_at = datetime.now(UTC)
                review.processing_time_ms = int((time.monotonic() - start_time) * 1000)
                await session.commit()
                return

            tokenized = tokenize_hunks(diff_hunks)
            chunked = smart_chunk(tokenized)

            review.files_analyzed = chunked.files_changed
            review.hunks_analyzed = chunked.total_hunks

            blast_radius = await analyze_blast_radius(
                tokenized, vcs, repo.full_name, review.head_sha
            )

            policy_result = await evaluate_policies(
                tokenized, session, repo.policy_pack_id
            )

            review_result = await run_review(
                chunked, policy_result, blast_radius
            )

            existing_hashes: set[str] = set()
            comments = generate_comments(review_result, existing_hashes)

            for comment in comments:
                db_comment = ReviewComment(
                    review_id=review.id,
                    file_path=comment.file_path,
                    line_start=comment.line_start,
                    line_end=comment.line_end,
                    severity=comment.severity,
                    category=comment.category,
                    title=comment.title,
                    body=comment.body,
                    suggestion=comment.suggestion,
                    evidence=comment.evidence,
                    content_hash=comment.content_hash,
                )
                session.add(db_comment)

            try:
                vcs_comments = [
                    ReviewCommentPayload(
                        file_path=c.file_path,
                        line=c.line_start,
                        body=format_for_vcs(c),
                    )
                    for c in comments
                ]
                if vcs_comments:
                    await vcs.post_review_comment(
                        repo.full_name,
                        review.pr_number,
                        review.head_sha,
                        vcs_comments,
                    )

                summary = generate_summary(comments)
                await vcs.post_review_summary(
                    repo.full_name, review.pr_number, summary
                )
            except Exception:
                logger.exception("vcs_comment_post_failed", review_id=review_id)

            review.status = ReviewStatus.COMPLETED
            review.completed_at = datetime.now(UTC)
            review.processing_time_ms = int((time.monotonic() - start_time) * 1000)

        except Exception as exc:
            logger.exception("review_processing_failed", review_id=review_id)
            review.status = ReviewStatus.FAILED
            review.error_message = str(exc)[:1000]
            review.completed_at = datetime.now(UTC)
            review.processing_time_ms = int((time.monotonic() - start_time) * 1000)

        await session.commit()


@celery_app.task(
    name="app.workers.tasks.process_pr_review",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def process_pr_review(self, review_id: str) -> dict:
    """Process a PR review asynchronously."""
    logger.info("starting_pr_review", review_id=review_id, task_id=self.request.id)
    try:
        asyncio.run(_process_review(review_id))
        return {"status": "completed", "review_id": review_id}
    except Exception as exc:
        logger.exception("review_task_failed", review_id=review_id)
        raise self.retry(exc=exc)


@celery_app.task(name="app.workers.tasks.process_feedback")
def process_feedback(comment_id: str, outcome: str) -> dict:
    """Process feedback on a review comment."""
    from app.services.feedback_tracker import record_feedback

    async def _run():
        session_factory = _get_async_session()
        async with session_factory() as session:
            await record_feedback(session, comment_id, outcome)
            await session.commit()

    asyncio.run(_run())
    return {"status": "processed", "comment_id": comment_id, "outcome": outcome}
