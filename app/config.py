"""Application configuration via pydantic-settings."""

from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class Severity(StrEnum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: Environment = Environment.DEVELOPMENT
    app_debug: bool = False
    app_log_level: str = "INFO"
    app_secret_key: str = "change-me"

    # Database
    database_url: str = "postgresql+asyncpg://diffmaster:diffmaster@localhost:5432/diffmaster"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_max_tokens: int = 4096

    # GitHub
    github_app_id: str = ""
    github_app_private_key_path: str = ""
    github_webhook_secret: str = ""

    # GitLab
    gitlab_url: str = "https://gitlab.com"
    gitlab_token: str = ""
    gitlab_webhook_secret: str = ""

    # Review
    max_comments_per_pr: int = 25
    comment_dedup_enabled: bool = True
    suppress_style_only: bool = False
    min_severity: Severity = Severity.INFO

    # RAG
    vector_similarity_threshold: float = 0.75
    rag_top_k: int = 10
    embedding_dimensions: int = 1536

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
