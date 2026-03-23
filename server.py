"""
DiffMaster FastAPI Server — Entry Point

Starts the Uvicorn ASGI server for the DiffMaster API.

Usage:
    python server.py

Environment:
    HOST            Bind address (default: 0.0.0.0)
    PORT            Listen port (default: 8000)
    WEBHOOK_SECRET  HMAC secret for GitHub / GitLab signature validation
    REDIS_URL       Redis broker URL for Celery task queue
    GEMINI_API_KEY  (or GROQ_API_KEY) for LLM access
    GITHUB_TOKEN    GitHub API token for posting review comments
    GITLAB_TOKEN    GitLab API token (if using GitLab)

Worker (required for async task processing):
    celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

Periodic retention (optional, run via Celery Beat):
    celery -A app.workers.celery_app beat --loglevel=info
"""

import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    uvicorn.run(
        "app.api.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
        log_level="info",
    )
