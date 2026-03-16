"""Review management API endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.comment import ReviewComment
from app.models.review import Review
from app.schemas.comment import CommentOut, FeedbackUpdate
from app.schemas.review import ReviewDetailOut, ReviewListOut, ReviewOut
from app.services.feedback_tracker import (
    get_category_stats,
    get_repo_feedback_stats,
)

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("", response_model=ReviewListOut)
async def list_reviews(
    repository_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Review)

    if repository_id:
        stmt = stmt.where(Review.repository_id == repository_id)
    if status:
        stmt = stmt.where(Review.status == status)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = stmt.order_by(Review.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)

    result = await session.execute(stmt)
    reviews = list(result.scalars().all())

    return ReviewListOut(
        reviews=[ReviewOut.model_validate(r) for r in reviews],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{review_id}", response_model=ReviewDetailOut)
async def get_review(
    review_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Review).where(Review.id == review_id)
    result = await session.execute(stmt)
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    return ReviewDetailOut.model_validate(review)


@router.get("/{review_id}/comments", response_model=list[CommentOut])
async def get_review_comments(
    review_id: uuid.UUID,
    severity: str | None = None,
    category: str | None = None,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(ReviewComment).where(ReviewComment.review_id == review_id)

    if severity:
        stmt = stmt.where(ReviewComment.severity == severity)
    if category:
        stmt = stmt.where(ReviewComment.category == category)

    stmt = stmt.order_by(ReviewComment.file_path, ReviewComment.line_start)

    result = await session.execute(stmt)
    comments = list(result.scalars().all())

    return [CommentOut.model_validate(c) for c in comments]


@router.patch("/{review_id}/comments/{comment_id}/feedback")
async def update_comment_feedback(
    review_id: uuid.UUID,
    comment_id: uuid.UUID,
    feedback: FeedbackUpdate,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(ReviewComment).where(
        ReviewComment.id == comment_id,
        ReviewComment.review_id == review_id,
    )
    result = await session.execute(stmt)
    comment = result.scalar_one_or_none()

    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    valid_outcomes = {"accepted", "rejected", "resolved"}
    if feedback.feedback not in valid_outcomes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid feedback. Must be one of: {valid_outcomes}",
        )

    comment.feedback = feedback.feedback
    await session.commit()

    return {"status": "updated", "comment_id": str(comment_id), "feedback": feedback.feedback}


@router.get("/{review_id}/stats")
async def get_review_stats(
    review_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    stmt = select(Review).where(Review.id == review_id)
    result = await session.execute(stmt)
    review = result.scalar_one_or_none()

    if not review:
        raise HTTPException(status_code=404, detail="Review not found")

    stats = await get_repo_feedback_stats(session, str(review.repository_id))
    category_stats = await get_category_stats(session, str(review.repository_id))

    return {
        "review_id": str(review_id),
        "repository_id": str(review.repository_id),
        "feedback_stats": {
            "total_comments": stats.total_comments,
            "accepted": stats.accepted,
            "rejected": stats.rejected,
            "resolved": stats.resolved,
            "pending": stats.pending,
            "acceptance_rate": stats.acceptance_rate,
            "noise_rate": stats.noise_rate,
        },
        "category_breakdown": [
            {
                "category": cs.category,
                "total": cs.total,
                "accepted": cs.accepted,
                "rejected": cs.rejected,
                "acceptance_rate": cs.acceptance_rate,
            }
            for cs in category_stats
        ],
    }
