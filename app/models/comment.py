"""ReviewComment model - line-anchored review comments."""

import uuid
from enum import Enum as PyEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class CommentSeverity(str, PyEnum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


class CommentCategory(str, PyEnum):
    SECURITY = "security"
    RELIABILITY = "reliability"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


class FeedbackOutcome(str, PyEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    RESOLVED = "resolved"


class ReviewComment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "review_comments"

    review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reviews.id"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, nullable=False)
    line_end: Mapped[int] = mapped_column(Integer, nullable=False)
    severity: Mapped[str] = mapped_column(
        Enum(CommentSeverity, name="comment_severity"), nullable=False
    )
    category: Mapped[str] = mapped_column(
        Enum(CommentCategory, name="comment_category"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    vcs_comment_id: Mapped[str | None] = mapped_column(String(255))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)
    feedback: Mapped[str] = mapped_column(
        Enum(FeedbackOutcome, name="feedback_outcome"),
        default=FeedbackOutcome.PENDING,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding = mapped_column(Vector(1536), nullable=True)

    review = relationship("Review", back_populates="comments")

    def __repr__(self) -> str:
        return f"<ReviewComment [{self.severity}] {self.file_path}:{self.line_start}>"
