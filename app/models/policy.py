"""Policy models - org/repo-level review policy packs."""

import uuid
from enum import StrEnum

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class PolicyScope(StrEnum):
    GLOBAL = "global"
    ORGANIZATION = "organization"
    REPOSITORY = "repository"


class Policy(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "policies"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str] = mapped_column(
        Enum(PolicyScope, name="policy_scope"), default=PolicyScope.GLOBAL
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)

    rules = relationship("PolicyRule", back_populates="policy", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Policy {self.name}>"


class RuleType(StrEnum):
    FORBIDDEN_API = "forbidden_api"
    REQUIRED_PATTERN = "required_pattern"
    SECRET_DETECTION = "secret_detection"
    LOGGING_STANDARD = "logging_standard"
    PERFORMANCE_CONSTRAINT = "performance_constraint"
    CUSTOM_REGEX = "custom_regex"


class PolicyRule(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "policy_rules"

    policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("policies.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    rule_type: Mapped[str] = mapped_column(
        Enum(RuleType, name="rule_type"), nullable=False
    )
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="WARNING")
    file_glob: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[dict | None] = mapped_column(JSONB)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    policy = relationship("Policy", back_populates="rules")

    def __repr__(self) -> str:
        return f"<PolicyRule {self.name} ({self.rule_type})>"
