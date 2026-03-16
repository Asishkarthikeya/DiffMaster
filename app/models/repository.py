"""Repository model - tracks onboarded repositories."""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Repository(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "repositories"

    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # github | gitlab
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), default="main")
    language: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    webhook_active: Mapped[bool] = mapped_column(Boolean, default=True)
    policy_pack_id: Mapped[str | None] = mapped_column(String(255))

    reviews = relationship("Review", back_populates="repository", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Repository {self.full_name}>"
