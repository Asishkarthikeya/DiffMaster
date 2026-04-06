import os


class Settings:
    """Config that reads from environment variables (GitHub Secrets or server env)."""

    def __init__(self):
        # --- LLM Keys ---
        self.GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
        self.GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
        self.GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-preview-05-20")

        # --- GitHub (Action mode) ---
        self.GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
        self.GITHUB_REPOSITORY: str = os.getenv("GITHUB_REPOSITORY", "")
        self.PR_NUMBER: str = os.getenv("PR_NUMBER", "0")
        self.SEVERITY_FILTER: str = os.getenv("SEVERITY_FILTER", "INFO")

        # --- FastAPI Server ---
        self.HOST: str = os.getenv("HOST", "0.0.0.0")
        self.PORT: int = int(os.getenv("PORT", "8000"))
        self.WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

        # --- Rate Limiting ---
        self.RATE_LIMIT_REQUESTS: int = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
        self.RATE_LIMIT_WINDOW: int = int(os.getenv("RATE_LIMIT_WINDOW", "3600"))

        # --- Celery / Redis (Task Queue) ---
        self.REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.CELERY_BROKER_URL: str = os.getenv(
            "CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://localhost:6379/0")
        )
        self.CELERY_RESULT_BACKEND: str = os.getenv(
            "CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://localhost:6379/1")
        )

        # --- FR-4: Audit Logging ---
        self.AUDIT_LOG_PATH: str = os.getenv("AUDIT_LOG_PATH", "./logs/audit.jsonl")
        self.AUDIT_LOG_RETENTION_DAYS: int = int(os.getenv("AUDIT_LOG_RETENTION_DAYS", "90"))
        self.ENABLE_AUDIT_LOG: bool = os.getenv("ENABLE_AUDIT_LOG", "true").lower() == "true"

        # --- FR-4: Service Account ---
        self.SERVICE_ACCOUNT_ID: str = os.getenv("SERVICE_ACCOUNT_ID", "")
        self.SERVICE_ACCOUNT_KEY: str = os.getenv("SERVICE_ACCOUNT_KEY", "")

        # --- pgvector / PostgreSQL ---
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "")
        self.USE_PGVECTOR: bool = os.getenv("USE_PGVECTOR", "false").lower() == "true"

        # --- GitLab ---
        self.GITLAB_TOKEN: str = os.getenv("GITLAB_TOKEN", "")
        self.GITLAB_URL: str = os.getenv("GITLAB_URL", "https://gitlab.com")

        # --- Cache / Retention ---
        self.CACHE_RETENTION_DAYS: int = int(os.getenv("CACHE_RETENTION_DAYS", "30"))
        self.REVIEW_RETENTION_DAYS: int = int(os.getenv("REVIEW_RETENTION_DAYS", "90"))


settings = Settings()

