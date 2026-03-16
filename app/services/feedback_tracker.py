"""Feedback Loop Tracker - learn from accepted/rejected comments per repository."""

from dataclasses import dataclass

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.comment import FeedbackOutcome, ReviewComment

logger = structlog.get_logger()


@dataclass
class FeedbackStats:
    total_comments: int = 0
    accepted: int = 0
    rejected: int = 0
    resolved: int = 0
    pending: int = 0

    @property
    def acceptance_rate(self) -> float:
        responded = self.accepted + self.rejected
        if responded == 0:
            return 0.0
        return self.accepted / responded

    @property
    def noise_rate(self) -> float:
        responded = self.accepted + self.rejected
        if responded == 0:
            return 0.0
        return self.rejected / responded


@dataclass
class CategoryStats:
    category: str
    total: int = 0
    accepted: int = 0
    rejected: int = 0
    acceptance_rate: float = 0.0


async def record_feedback(
    session: AsyncSession,
    comment_id: str,
    outcome: str,
) -> ReviewComment | None:
    """Record developer feedback on a review comment."""
    stmt = select(ReviewComment).where(ReviewComment.id == comment_id)
    result = await session.execute(stmt)
    comment = result.scalar_one_or_none()

    if not comment:
        return None

    comment.feedback = outcome
    await session.flush()

    logger.info(
        "feedback_recorded",
        comment_id=comment_id,
        outcome=outcome,
        severity=comment.severity,
        category=comment.category,
    )

    return comment


async def get_repo_feedback_stats(
    session: AsyncSession,
    repository_id: str,
) -> FeedbackStats:
    """Get aggregate feedback statistics for a repository."""
    from app.models.review import Review

    subq = select(Review.id).where(Review.repository_id == repository_id).subquery()

    stmt = (
        select(
            ReviewComment.feedback,
            func.count(ReviewComment.id).label("count"),
        )
        .where(ReviewComment.review_id.in_(select(subq)))
        .group_by(ReviewComment.feedback)
    )

    result = await session.execute(stmt)
    rows = result.all()

    stats = FeedbackStats()
    for feedback, count in rows:
        stats.total_comments += count
        if feedback == FeedbackOutcome.ACCEPTED:
            stats.accepted = count
        elif feedback == FeedbackOutcome.REJECTED:
            stats.rejected = count
        elif feedback == FeedbackOutcome.RESOLVED:
            stats.resolved = count
        elif feedback == FeedbackOutcome.PENDING:
            stats.pending = count

    return stats


async def get_category_stats(
    session: AsyncSession,
    repository_id: str,
) -> list[CategoryStats]:
    """Get per-category feedback breakdown for noise tuning."""
    from app.models.review import Review

    subq = select(Review.id).where(Review.repository_id == repository_id).subquery()

    stmt = (
        select(
            ReviewComment.category,
            ReviewComment.feedback,
            func.count(ReviewComment.id).label("count"),
        )
        .where(ReviewComment.review_id.in_(select(subq)))
        .group_by(ReviewComment.category, ReviewComment.feedback)
    )

    result = await session.execute(stmt)
    rows = result.all()

    category_map: dict[str, CategoryStats] = {}
    for category, feedback, count in rows:
        if category not in category_map:
            category_map[category] = CategoryStats(category=category)
        cs = category_map[category]
        cs.total += count
        if feedback == FeedbackOutcome.ACCEPTED:
            cs.accepted += count
        elif feedback == FeedbackOutcome.REJECTED:
            cs.rejected += count

    for cs in category_map.values():
        responded = cs.accepted + cs.rejected
        cs.acceptance_rate = cs.accepted / responded if responded > 0 else 0.0

    return list(category_map.values())
