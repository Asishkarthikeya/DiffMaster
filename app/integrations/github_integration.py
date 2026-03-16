"""GitHub VCS integration using PyGithub and httpx."""

import httpx
import structlog
from unidiff import PatchSet

from app.config import get_settings
from app.integrations.base import (
    DiffHunk,
    FileContent,
    PullRequestInfo,
    RepoMetadata,
    ReviewCommentPayload,
    VCSIntegration,
)

logger = structlog.get_logger()
settings = get_settings()

GITHUB_API_BASE = "https://api.github.com"


class GitHubIntegration(VCSIntegration):
    def __init__(self, token: str | None = None):
        self._token = token
        self._headers = {
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=GITHUB_API_BASE,
            headers=self._headers,
            timeout=30.0,
        )

    async def get_pull_request(self, repo_full_name: str, pr_number: int) -> PullRequestInfo:
        async with self._client() as client:
            resp = await client.get(f"/repos/{repo_full_name}/pulls/{pr_number}")
            resp.raise_for_status()
            data = resp.json()

        return PullRequestInfo(
            number=data["number"],
            title=data["title"],
            author=data["user"]["login"],
            head_sha=data["head"]["sha"],
            base_sha=data["base"]["sha"],
            base_branch=data["base"]["ref"],
            head_branch=data["head"]["ref"],
            body=data.get("body") or "",
            additions=data.get("additions", 0),
            deletions=data.get("deletions", 0),
            changed_files=data.get("changed_files", 0),
        )

    async def get_diff(self, repo_full_name: str, pr_number: int) -> list[DiffHunk]:
        headers = {**self._headers, "Accept": "application/vnd.github.v3.diff"}
        async with httpx.AsyncClient(
            base_url=GITHUB_API_BASE, headers=headers, timeout=60.0
        ) as client:
            resp = await client.get(f"/repos/{repo_full_name}/pulls/{pr_number}")
            resp.raise_for_status()
            raw_diff = resp.text

        hunks: list[DiffHunk] = []
        try:
            patch_set = PatchSet(raw_diff)
            for patched_file in patch_set:
                for hunk in patched_file:
                    hunks.append(
                        DiffHunk(
                            file_path=patched_file.path,
                            old_start=hunk.source_start,
                            old_count=hunk.source_length,
                            new_start=hunk.target_start,
                            new_count=hunk.target_length,
                            content=str(hunk),
                            header=hunk.section_header or "",
                            is_new_file=patched_file.is_added_file,
                            is_deleted_file=patched_file.is_removed_file,
                            is_binary=patched_file.is_binary_file,
                        )
                    )
        except Exception:
            logger.exception("failed_to_parse_diff", repo=repo_full_name, pr=pr_number)

        return hunks

    async def get_file_content(
        self, repo_full_name: str, path: str, ref: str
    ) -> FileContent:
        async with self._client() as client:
            resp = await client.get(
                f"/repos/{repo_full_name}/contents/{path}",
                params={"ref": ref},
                headers={**self._headers, "Accept": "application/vnd.github.v3.raw"},
            )
            resp.raise_for_status()
            content = resp.text

        return FileContent(path=path, content=content, size=len(content))

    async def get_repo_metadata(self, repo_full_name: str) -> RepoMetadata:
        async with self._client() as client:
            resp = await client.get(f"/repos/{repo_full_name}")
            resp.raise_for_status()
            data = resp.json()

        return RepoMetadata(
            full_name=data["full_name"],
            owner=data["owner"]["login"],
            name=data["name"],
            default_branch=data.get("default_branch", "main"),
            language=data.get("language"),
        )

    async def post_review_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[ReviewCommentPayload],
    ) -> list[str]:
        comment_ids: list[str] = []
        async with self._client() as client:
            review_body = {
                "commit_id": commit_sha,
                "event": "COMMENT",
                "comments": [
                    {
                        "path": c.file_path,
                        "line": c.line,
                        "side": c.side,
                        "body": c.body,
                    }
                    for c in comments
                ],
            }
            resp = await client.post(
                f"/repos/{repo_full_name}/pulls/{pr_number}/reviews",
                json=review_body,
            )
            resp.raise_for_status()
            data = resp.json()
            comment_ids.append(str(data.get("id", "")))

        return comment_ids

    async def post_review_summary(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str,
    ) -> str:
        async with self._client() as client:
            resp = await client.post(
                f"/repos/{repo_full_name}/issues/{pr_number}/comments",
                json={"body": body},
            )
            resp.raise_for_status()
            return str(resp.json().get("id", ""))
