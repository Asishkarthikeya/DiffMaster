"""Tests for webhook validation."""

import hashlib
import hmac

import pytest

from app.integrations.webhook_validator import (
    validate_github_signature,
    validate_gitlab_token,
)


class TestGitHubSignatureValidation:
    def test_valid_sha256_signature(self):
        payload = b'{"action": "opened"}'
        secret = "mysecret"
        sig = "sha256=" + hmac.new(
            secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        assert validate_github_signature(payload, sig, secret) is True

    def test_valid_sha1_signature(self):
        payload = b'{"action": "opened"}'
        secret = "mysecret"
        sig = "sha1=" + hmac.new(
            secret.encode(), payload, hashlib.sha1
        ).hexdigest()
        assert validate_github_signature(payload, sig, secret) is True

    def test_invalid_signature(self):
        payload = b'{"action": "opened"}'
        assert validate_github_signature(payload, "sha256=invalid", "secret") is False

    def test_empty_signature(self):
        assert validate_github_signature(b"payload", "", "secret") is False

    def test_empty_secret(self):
        assert validate_github_signature(b"payload", "sha256=abc", "") is False

    def test_unsupported_algorithm(self):
        assert validate_github_signature(b"payload", "md5=abc", "secret") is False


class TestGitLabTokenValidation:
    def test_valid_token(self):
        assert validate_gitlab_token("my-secret-token", "my-secret-token") is True

    def test_invalid_token(self):
        assert validate_gitlab_token("wrong-token", "my-secret-token") is False

    def test_empty_token(self):
        assert validate_gitlab_token("", "secret") is False

    def test_empty_secret(self):
        assert validate_gitlab_token("token", "") is False
