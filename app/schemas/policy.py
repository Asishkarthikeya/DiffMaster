"""Schemas for policy management."""

import uuid
from datetime import datetime

from pydantic import BaseModel


class PolicyRuleCreate(BaseModel):
    name: str
    rule_type: str
    pattern: str
    message: str
    severity: str = "WARNING"
    file_glob: str | None = None
    config: dict | None = None


class PolicyRuleOut(BaseModel):
    id: uuid.UUID
    name: str
    rule_type: str
    pattern: str
    message: str
    severity: str
    file_glob: str | None
    config: dict | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PolicyCreate(BaseModel):
    name: str
    description: str | None = None
    scope: str = "global"
    priority: int = 0
    rules: list[PolicyRuleCreate] = []


class PolicyUpdate(BaseModel):
    description: str | None = None
    is_active: bool | None = None
    priority: int | None = None


class PolicyOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    scope: str
    is_active: bool
    priority: int
    rules: list[PolicyRuleOut] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PolicyListOut(BaseModel):
    policies: list[PolicyOut]
    total: int
