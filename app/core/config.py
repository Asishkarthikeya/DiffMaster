import os


class Settings:
    """Config that reads from environment variables (GitHub Secrets or server env)."""

    # --- LLM Keys ---
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-05-20")

    # --- GitHub (Action mode) ---
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_REPOSITORY: str = os.getenv("GITHUB_REPOSITORY", "")
    PR_NUMBER: str = os.getenv("PR_NUMBER", "0")
    SEVERITY_FILTER: str = os.getenv("SEVERITY_FILTER", "INFO")

    # --- FastAPI Server ---
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

    # --- Rate Limiting ---
    RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
    RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "3600"))  # seconds

    # --- Celery / Redis (Task Queue) ---
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    CELERY_BROKER_URL: str = os.getenv(
        "CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    CELERY_RESULT_BACKEND: str = os.getenv(
        "CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://localhost:6379/1")
    )

    # --- FR-4: Audit Logging ---
    AUDIT_LOG_PATH: str = os.getenv("AUDIT_LOG_PATH", "./logs/audit.jsonl")
    AUDIT_LOG_RETENTION_DAYS: int = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "90"))
    ENABLE_AUDIT_LOG: bool = os.getenv("ENABLE_AUDIT_LOG", "true").lower() == "true"

    # --- FR-4: Service Account ---
    SERVICE_ACCOUNT_ID: str = os.getenv("SERVICE_ACCOUNT_ID", "")
    SERVICE_ACCOUNT_KEY: str = os.getenv("SERVICE_ACCOUNT_KEY", "")

    # --- pgvector / PostgreSQL ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    USE_PGVECTOR: bool = os.getenv("USE_PGVECTOR", "false").lower() == "true"

    # --- GitLab ---
    GITLAB_TOKEN: str = os.getenv("GITLAB_TOKEN", "")
    GITLAB_URL: str = os.getenv("GITLAB_URL", "https://gitlab.com")

    # --- Cache / Retention ---
    CACHE_RETENTION_DAYS: int = int(os.getenv("CACHE_RETENTION_DAYS", "30"))
    REVIEW_RETENTION_DAYS: int = int(os.getenv("REVIEW_RETENTION_DAYS", "90"))


settings = Settings()
