"""Tests for the FastAPI application and API endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestRootEndpoint:
    def test_root_returns_service_info(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "DiffMaster"
        assert "version" in data


class TestHealthEndpoints:
    def test_readiness_check(self, client):
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json()["ready"] is True


class TestWebhookEndpoints:
    def test_github_webhook_non_pr_event(self, client):
        response = client.post(
            "/api/v1/webhooks/github",
            content=b'{"action": "created"}',
            headers={
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_gitlab_webhook_non_mr_event(self, client):
        payload = {
            "object_kind": "push",
            "event_type": "push",
            "project": {
                "id": 1,
                "name": "test",
                "path_with_namespace": "org/test",
                "default_branch": "main",
            },
            "object_attributes": {
                "iid": 1,
                "title": "test",
                "state": "opened",
                "author_id": 1,
                "source_branch": "feature",
                "target_branch": "main",
            },
        }
        response = client.post(
            "/api/v1/webhooks/gitlab",
            json=payload,
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"


class TestOpenAPISchema:
    def test_openapi_schema_available(self, client):
        response = client.get("/openapi.json")
        assert response.status_code == 200
        schema = response.json()
        assert schema["info"]["title"] == "DiffMaster"
        assert "paths" in schema
