"""Webhook signature validation for GitHub and GitLab."""

import hashlib
import hmac

import structlog

logger = structlog.get_logger()


def validate_github_signature(payload: bytes, signature: str, secret: str) -> bool:
    if not signature or not secret:
        return False

    if signature.startswith("sha256="):
        expected = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    if signature.startswith("sha1="):
        expected = "sha1=" + hmac.new(
            secret.encode(), payload, hashlib.sha1
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    return False


def validate_gitlab_token(token: str, secret: str) -> bool:
    if not token or not secret:
        return False
    return hmac.compare_digest(token, secret)
