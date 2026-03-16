"""Shared test fixtures."""

import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.integrations.base import DiffHunk, PullRequestInfo, RepoMetadata
from app.main import app


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_diff_hunks() -> list[DiffHunk]:
    return [
        DiffHunk(
            file_path="app/auth.py",
            old_start=10,
            old_count=5,
            new_start=10,
            new_count=8,
            content=(
                "@@ -10,5 +10,8 @@\n"
                " def authenticate(user, password):\n"
                "-    return check_password(user, password)\n"
                "+    api_key = 'sk-secret-key-12345678'\n"
                "+    result = eval(user_input)\n"
                "+    return check_password(user, password)\n"
                "+    # Added new auth logic\n"
            ),
        ),
        DiffHunk(
            file_path="app/utils.py",
            old_start=1,
            old_count=3,
            new_start=1,
            new_count=5,
            content=(
                "@@ -1,3 +1,5 @@\n"
                " import os\n"
                "+import subprocess\n"
                "+result = os.system('echo hello')\n"
                " def helper():\n"
                "     pass\n"
            ),
        ),
        DiffHunk(
            file_path="app/models.py",
            old_start=20,
            old_count=3,
            new_start=20,
            new_count=4,
            content=(
                "@@ -20,3 +20,4 @@\n"
                " class User:\n"
                "     name: str\n"
                "+    email: str\n"
                "     age: int\n"
            ),
            is_new_file=False,
        ),
    ]


@pytest.fixture
def sample_pr_info() -> PullRequestInfo:
    return PullRequestInfo(
        number=42,
        title="Add authentication improvements",
        author="developer",
        head_sha="abc123def456",
        base_sha="000111222333",
        base_branch="main",
        head_branch="feature/auth",
        body="Improving auth flow",
        additions=50,
        deletions=10,
        changed_files=3,
    )


@pytest.fixture
def sample_repo_metadata() -> RepoMetadata:
    return RepoMetadata(
        full_name="org/repo",
        owner="org",
        name="repo",
        default_branch="main",
        language="Python",
    )


@pytest.fixture
def mock_vcs():
    vcs = AsyncMock()
    vcs.get_pull_request = AsyncMock()
    vcs.get_diff = AsyncMock()
    vcs.get_file_content = AsyncMock()
    vcs.get_repo_metadata = AsyncMock()
    vcs.post_review_comment = AsyncMock(return_value=["123"])
    vcs.post_review_summary = AsyncMock(return_value="456")
    return vcs
