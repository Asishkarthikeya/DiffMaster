"""Review model - tracks each PR review."""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class ReviewStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Review(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "reviews"

    repository_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repositories.id"), nullable=False
    )
    pr_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pr_title: Mapped[str] = mapped_column(String(500), nullable=False)
    pr_author: Mapped[str] = mapped_column(String(255), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(ReviewStatus, name="review_status"),
        default=ReviewStatus.PENDING,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    files_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    hunks_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    processing_time_ms: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    celery_task_id: Mapped[str | None] = mapped_column(String(255))

    repository = relationship("Repository", back_populates="reviews")
    comments = relationship("ReviewComment", back_populates="review", lazy="selectin")

    @property
    def comment_count(self) -> int:
        return len(self.comments) if self.comments else 0

    def __repr__(self) -> str:
        return f"<Review PR#{self.pr_number} ({self.status})>"
