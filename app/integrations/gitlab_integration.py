"""GitLab VCS integration."""

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


class GitLabIntegration(VCSIntegration):
    def __init__(self, url: str | None = None, token: str | None = None):
        self._base_url = (url or settings.gitlab_url).rstrip("/") + "/api/v4"
        self._token = token or settings.gitlab_token
        self._headers = {"PRIVATE-TOKEN": self._token} if self._token else {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=30.0,
        )

    @staticmethod
    def _encode_project(full_name: str) -> str:
        return full_name.replace("/", "%2F")

    async def get_pull_request(self, repo_full_name: str, pr_number: int) -> PullRequestInfo:
        project = self._encode_project(repo_full_name)
        async with self._client() as client:
            resp = await client.get(
                f"/projects/{project}/merge_requests/{pr_number}"
            )
            resp.raise_for_status()
            data = resp.json()

        diff_refs = data.get("diff_refs", {})
        return PullRequestInfo(
            number=data["iid"],
            title=data["title"],
            author=data["author"]["username"],
            head_sha=diff_refs.get("head_sha", ""),
            base_sha=diff_refs.get("base_sha", ""),
            base_branch=data["target_branch"],
            head_branch=data["source_branch"],
            body=data.get("description") or "",
        )

    async def get_diff(self, repo_full_name: str, pr_number: int) -> list[DiffHunk]:
        project = self._encode_project(repo_full_name)
        async with self._client() as client:
            resp = await client.get(
                f"/projects/{project}/merge_requests/{pr_number}/changes"
            )
            resp.raise_for_status()
            data = resp.json()

        hunks: list[DiffHunk] = []
        for change in data.get("changes", []):
            diff_text = change.get("diff", "")
            if not diff_text:
                continue
            header = f"--- a/{change['old_path']}\n+++ b/{change['new_path']}\n"
            try:
                patch = PatchSet(header + diff_text)
                for pf in patch:
                    for hunk in pf:
                        hunks.append(
                            DiffHunk(
                                file_path=change["new_path"],
                                old_start=hunk.source_start,
                                old_count=hunk.source_length,
                                new_start=hunk.target_start,
                                new_count=hunk.target_length,
                                content=str(hunk),
                                header=hunk.section_header or "",
                                is_new_file=change.get("new_file", False),
                                is_deleted_file=change.get("deleted_file", False),
                            )
                        )
            except Exception:
                logger.exception("gitlab_diff_parse_error", file=change.get("new_path"))

        return hunks

    async def get_file_content(
        self, repo_full_name: str, path: str, ref: str
    ) -> FileContent:
        project = self._encode_project(repo_full_name)
        encoded_path = path.replace("/", "%2F")
        async with self._client() as client:
            resp = await client.get(
                f"/projects/{project}/repository/files/{encoded_path}/raw",
                params={"ref": ref},
            )
            resp.raise_for_status()

        return FileContent(path=path, content=resp.text, size=len(resp.text))

    async def get_repo_metadata(self, repo_full_name: str) -> RepoMetadata:
        project = self._encode_project(repo_full_name)
        async with self._client() as client:
            resp = await client.get(f"/projects/{project}")
            resp.raise_for_status()
            data = resp.json()

        ns = data.get("namespace", {})
        return RepoMetadata(
            full_name=data["path_with_namespace"],
            owner=ns.get("path", ""),
            name=data["name"],
            default_branch=data.get("default_branch", "main"),
        )

    async def post_review_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[ReviewCommentPayload],
    ) -> list[str]:
        project = self._encode_project(repo_full_name)
        comment_ids: list[str] = []
        async with self._client() as client:
            for c in comments:
                body = {
                    "body": c.body,
                    "position": {
                        "position_type": "text",
                        "new_path": c.file_path,
                        "new_line": c.line,
                        "base_sha": "",
                        "head_sha": commit_sha,
                        "start_sha": "",
                    },
                }
                resp = await client.post(
                    f"/projects/{project}/merge_requests/{pr_number}/discussions",
                    json=body,
                )
                if resp.is_success:
                    comment_ids.append(str(resp.json().get("id", "")))
                else:
                    logger.warning("gitlab_comment_failed", status=resp.status_code)

        return comment_ids

    async def post_review_summary(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str,
    ) -> str:
        project = self._encode_project(repo_full_name)
        async with self._client() as client:
            resp = await client.post(
                f"/projects/{project}/merge_requests/{pr_number}/notes",
                json={"body": body},
            )
            resp.raise_for_status()
            return str(resp.json().get("id", ""))
