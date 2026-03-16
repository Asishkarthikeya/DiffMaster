"""Schemas for review API endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.comment import CommentOut


class ReviewOut(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    pr_number: int
    pr_title: str
    pr_author: str
    head_sha: str
    base_sha: str
    status: str
    files_analyzed: int
    hunks_analyzed: int
    processing_time_ms: int | None
    started_at: datetime | None
    completed_at: datetime | None
    comment_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReviewDetailOut(ReviewOut):
    comments: list[CommentOut] = []
    error_message: str | None = None


class ReviewListOut(BaseModel):
    reviews: list[ReviewOut]
    total: int
    page: int
    page_size: int
