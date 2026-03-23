"""
FR-4: SSO / Service Account Authentication Middleware

Provides API-level authentication for DiffMaster's FastAPI endpoints.

Supports multiple authentication modes:
1. Service Account (API Key): Header-based auth via X-API-Key
2. SSO / Bearer Token: OAuth2 / OIDC bearer token validation
3. Webhook Signatures: Handled separately in webhooks.py

Usage in routes:
    from app.api.middleware.auth import require_auth, require_admin

    @router.get("/audit/stats", dependencies=[Depends(require_auth)])
    async def audit_stats(): ...

Environment:
    SERVICE_ACCOUNT_ID    — Service account identifier
    SERVICE_ACCOUNT_KEY   — API key for service account auth
    SSO_JWKS_URL          — JWKS endpoint for JWT validation (optional)
    AUTH_DISABLED          — Set "true" to disable auth (dev mode only)
"""

import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.services.audit import get_audit_logger

logger = logging.getLogger("diffmaster.auth")

# Security scheme definitions (appear in OpenAPI docs)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

# Auth toggle (for local development only)
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").lower() == "true"


def _validate_api_key(api_key: str) -> dict:
    """
    Validate a service account API key.

    Returns actor info dict on success, raises HTTPException on failure.
    Uses constant-time comparison to prevent timing attacks.
    """
    if not settings.SERVICE_ACCOUNT_KEY:
        raise HTTPException(
            status_code=500,
            detail="Server misconfigured: SERVICE_ACCOUNT_KEY not set",
        )

    # Constant-time comparison
    key_valid = hmac.compare_digest(api_key, settings.SERVICE_ACCOUNT_KEY)
    if not key_valid:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return {
        "actor_id": settings.SERVICE_ACCOUNT_ID or "service-account",
        "auth_method": "api_key",
    }


def _validate_bearer_token(token: str) -> dict:
    """
    Validate a Bearer / SSO token.

    For JWT-based SSO: decodes and validates the token against JWKS.
    For simple bearer: validates against SERVICE_ACCOUNT_KEY.

    Returns actor info dict on success, raises HTTPException on failure.
    """
    sso_jwks_url = os.getenv("SSO_JWKS_URL", "")

    if sso_jwks_url:
        return _validate_jwt(token, sso_jwks_url)

    # Fallback: treat bearer token as API key
    return _validate_api_key(token)


def _validate_jwt(token: str, jwks_url: str) -> dict:
    """
    Validate a JWT token against a JWKS endpoint (standard OIDC/SSO flow).

    Supports any OIDC-compliant IdP (Okta, Auth0, Azure AD, Google Workspace).
    """
    try:
        import jwt
        from jwt import PyJWKClient

        jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            options={"verify_aud": False},  # Audience check can be added per-deployment
        )

        return {
            "actor_id": payload.get("sub", "unknown"),
            "email": payload.get("email", ""),
            "auth_method": "sso_jwt",
            "issuer": payload.get("iss", ""),
        }

    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="PyJWT is required for SSO. Run: pip install PyJWT[crypto]",
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")


async def get_current_user(
    api_key: Optional[str] = Security(api_key_header),
    bearer: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    request: Request = None,
) -> dict:
    """
    Extract and validate credentials from the request.

    Checks (in order):
    1. X-API-Key header (service account)
    2. Authorization: Bearer <token> (SSO / OAuth2)

    Returns:
        Actor info dict: {"actor_id": ..., "auth_method": ..., ...}
    """
    audit = get_audit_logger()

    # Dev mode bypass
    if AUTH_DISABLED:
        return {"actor_id": "dev-user", "auth_method": "disabled"}

    # Try API key first
    if api_key:
        try:
            actor = _validate_api_key(api_key)
            audit.log_event("auth_success", {
                "actor_id": actor["actor_id"],
                "method": "api_key",
                "path": request.url.path if request else "",
            })
            return actor
        except HTTPException:
            pass  # Fall through to try bearer

    # Try Bearer token
    if bearer and bearer.credentials:
        try:
            actor = _validate_bearer_token(bearer.credentials)
            audit.log_event("auth_success", {
                "actor_id": actor["actor_id"],
                "method": actor.get("auth_method", "bearer"),
                "path": request.url.path if request else "",
            })
            return actor
        except HTTPException:
            pass

    # No valid credentials
    audit.log_event("auth_failed", {
        "path": request.url.path if request else "",
        "reason": "no_valid_credentials",
    })
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Provide X-API-Key or Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ------------------------------------------------------------------
# Dependency shortcuts for route protection
# ------------------------------------------------------------------

async def require_auth(user: dict = Depends(get_current_user)) -> dict:
    """Dependency that requires any valid authentication."""
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency that requires admin-level access.
    Currently: only the configured service account is treated as admin.
    """
    if user.get("auth_method") == "disabled":
        return user

    if user.get("actor_id") != (settings.SERVICE_ACCOUNT_ID or "service-account"):
        raise HTTPException(status_code=403, detail="Admin access required")

    return user
