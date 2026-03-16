"""Schemas for repository management."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class RepositoryCreate(BaseModel):
    platform: str
    owner: str
    name: str
    default_branch: str = "main"
    language: str | None = None
    description: str | None = None
    policy_pack_id: str | None = None


class RepositoryUpdate(BaseModel):
    webhook_active: bool | None = None
    policy_pack_id: str | None = None
    default_branch: str | None = None
    language: str | None = None
    description: str | None = None


class RepositoryOut(BaseModel):
    id: uuid.UUID
    platform: str
    owner: str
    name: str
    full_name: str
    default_branch: str
    language: str | None
    description: str | None
    webhook_active: bool
    policy_pack_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RepositoryListOut(BaseModel):
    repositories: list[RepositoryOut]
    total: int
