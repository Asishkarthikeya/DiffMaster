"""Schemas for review comments."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class CommentOut(BaseModel):
    id: uuid.UUID
    file_path: str
    line_start: int
    line_end: int
    severity: str
    category: str
    title: str
    body: str
    suggestion: str | None
    evidence: str | None
    feedback: str
    is_duplicate: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackUpdate(BaseModel):
    feedback: str  # accepted | rejected | resolved
