import os


class Settings:
    """Lightweight config that reads from environment variables (GitHub Secrets)."""

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
    SEVERITY_FILTER: str = os.getenv("SEVERITY_FILTER", "INFO")
    GITHUB_REPOSITORY: str = os.getenv("GITHUB_REPOSITORY", "")
    PR_NUMBER: str = os.getenv("PR_NUMBER", "0")


settings = Settings()
