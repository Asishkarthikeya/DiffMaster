"""
DiffMaster FastAPI Server

Headless API middleware for receiving VCS webhook events and dispatching
async code review tasks via Celery + Redis.

Startup:
    uvicorn app.api.main:app --host 0.0.0.0 --port 8000
    # or via server.py:
    python server.py

Endpoints:
    POST /webhooks/github      — GitHub pull_request events
    POST /webhooks/gitlab      — GitLab Merge Request events
    POST /webhooks/bitbucket   — Bitbucket PR events
    GET  /health               — Health check
    GET  /audit/stats          — Audit log summary (FR-4, auth required)
    GET  /audit/events         — Query audit log (FR-4, auth required)
    POST /audit/enforce-retention — Trigger data retention (FR-4, admin)
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import webhooks
from app.api.middleware.auth import require_auth, require_admin
from app.core.config import settings
from app.services.audit import get_audit_logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Log server start/stop events to the audit trail."""
    audit = get_audit_logger()
    audit.log_event("server_start", {
        "host": settings.HOST,
        "port": settings.PORT,
        "service_account": settings.SERVICE_ACCOUNT_ID or "default",
    })
    yield
    audit.log_event("server_stop", {})


app = FastAPI(
    title="DiffMaster",
    description="Intelligent Automated Code Review API — headless middleware for PR review.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])


# ------------------------------------------------------------------
# Health check (no auth — used by load balancers)
# ------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health():
    """Liveness probe for load balancers and container orchestrators."""
    return {"status": "ok", "service": "diffmaster"}


@app.get("/", tags=["System"])
async def root():
    return {
        "service": "DiffMaster",
        "version": "1.0.0",
        "docs": "/docs",
        "webhooks": {
            "github": "/webhooks/github",
            "gitlab": "/webhooks/gitlab",
            "bitbucket": "/webhooks/bitbucket",
        },
    }


# ------------------------------------------------------------------
# FR-4: Audit log endpoints (auth required)
# ------------------------------------------------------------------

@app.get("/audit/stats", tags=["Audit"])
async def audit_stats(user: dict = Depends(require_auth)):
    """Return aggregate statistics from the audit log. Requires authentication."""
    audit = get_audit_logger()
    return audit.get_stats()


@app.get("/audit/events", tags=["Audit"])
async def audit_events(
    event_type: str = Query(None, description="Filter by event type"),
    repo: str = Query(None, description="Filter by repository"),
    limit: int = Query(100, ge=1, le=1000, description="Max entries to return"),
    user: dict = Depends(require_auth),
):
    """
    Query audit log entries with optional filters.
    Supports filtering by event type and repository for compliance reporting.
    Requires authentication.
    """
    audit = get_audit_logger()
    events = audit.query_events(event_type=event_type, repo=repo, limit=limit)
    return {"count": len(events), "events": events}


@app.post("/audit/enforce-retention", tags=["Audit"])
async def enforce_retention(user: dict = Depends(require_admin)):
    """
    Manually trigger audit log and cache retention enforcement.
    Removes entries older than AUDIT_LOG_RETENTION_DAYS.
    Requires admin (service account) authentication.
    """
    from app.services.retention import get_retention_policy
    policy = get_retention_policy()
    results = policy.run_all()
    return {"status": "completed", "results": results}
