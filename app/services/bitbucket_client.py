"""
Bitbucket Cloud VCS client for DiffMaster.
Supports Pull Request review workflows via the Atlassian API (atlassian-python-api).

Mirrors the GitHubClient / GitLabClient interface so the same review pipeline
works across all three VCS providers.
"""

import logging
from typing import Optional

logger = logging.getLogger("diffmaster.bitbucket")


class BitbucketPRFile:
    """Represents a file changed in a Bitbucket PR (mirrors PyGithub File object interface)."""

    def __init__(self, filename: str, status: str, patch: str):
        self.filename = filename
        self.status = status
        self.patch = patch


class BitbucketClient:
    """
    Bitbucket Cloud API client using atlassian-python-api.
    Interface-compatible with GitHubClient / GitLabClient for the VCS-agnostic pipeline.

    Supports:
    - PR file listing with diff patches
    - Raw file content at a specific commit
    - Inline PR comments
    - Policy file loading (.diffmaster.yml)

    Requires:
        BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD
        or BITBUCKET_TOKEN (OAuth/personal access token)
    """

    def __init__(
        self,
        username: Optional[str] = None,
        app_password: Optional[str] = None,
        token: Optional[str] = None,
        workspace: Optional[str] = None,
    ):
        try:
            from atlassian.bitbucket import Cloud as BitbucketCloud
        except ImportError:
            raise ImportError(
                "atlassian-python-api is required for Bitbucket support. "
                "Run: pip install atlassian-python-api"
            )

        import os

        self._username = username or os.getenv("BITBUCKET_USERNAME", "")
        self._app_password = app_password or os.getenv("BITBUCKET_APP_PASSWORD", "")
        self._token = token or os.getenv("BITBUCKET_TOKEN", "")
        self._workspace = workspace or os.getenv("BITBUCKET_WORKSPACE", "")

        if self._token:
            self._bb = BitbucketCloud(token=self._token, cloud=True)
        elif self._username and self._app_password:
            self._bb = BitbucketCloud(
                username=self._username,
                password=self._app_password,
                cloud=True,
            )
        else:
            raise RuntimeError(
                "Bitbucket credentials required. Set BITBUCKET_TOKEN or "
                "BITBUCKET_USERNAME + BITBUCKET_APP_PASSWORD."
            )

        logger.info("Bitbucket Cloud client initialized")

    # ------------------------------------------------------------------
    # Core interface (mirrors GitHubClient / GitLabClient)
    # ------------------------------------------------------------------

    def get_pull_request(self, repo_full_name: str, pr_number: int):
        """
        Fetch a Bitbucket Pull Request.
        repo_full_name: "workspace/repo_slug" format
        """
        workspace, repo_slug = self._parse_repo(repo_full_name)
        repo = self._bb.workspaces.get(workspace).repositories.get(repo_slug)
        return repo.pullrequests.get(pr_number)

    def get_pr_files(self, repo_full_name: str, pr_number: int) -> list[BitbucketPRFile]:
        """
        Return list of files changed in a Pull Request with their diffs.
        Uses the diffstat + diff endpoints.
        """
        import requests

        workspace, repo_slug = self._parse_repo(repo_full_name)

        # Get diffstat (list of changed files)
        diffstat_url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{workspace}/{repo_slug}/pullrequests/{pr_number}/diffstat"
        )
        diff_url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{workspace}/{repo_slug}/pullrequests/{pr_number}/diff"
        )

        headers = self._get_auth_headers()

        # Fetch diffstat for file list + statuses
        diffstat_resp = requests.get(diffstat_url, headers=headers)
        diffstat_resp.raise_for_status()
        diffstat = diffstat_resp.json()

        # Fetch the full unified diff
        diff_resp = requests.get(diff_url, headers=headers)
        diff_resp.raise_for_status()
        full_diff = diff_resp.text

        # Parse the full diff into per-file patches
        file_patches = self._split_diff_by_file(full_diff)

        files = []
        for entry in diffstat.get("values", []):
            new_path = entry.get("new", {}).get("path", "") if entry.get("new") else ""
            old_path = entry.get("old", {}).get("path", "") if entry.get("old") else ""
            status_raw = entry.get("status", "modified")

            status_map = {"added": "added", "removed": "deleted", "modified": "modified",
                          "renamed": "modified"}
            status = status_map.get(status_raw, "modified")
            filename = new_path or old_path

            files.append(BitbucketPRFile(
                filename=filename,
                status=status,
                patch=file_patches.get(filename, ""),
            ))

        return files

    def get_file_content(
        self, repo_full_name: str, file_path: str, ref: str
    ) -> Optional[str]:
        """Fetch raw file content at a specific commit ref."""
        import requests

        workspace, repo_slug = self._parse_repo(repo_full_name)
        url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{workspace}/{repo_slug}/src/{ref}/{file_path}"
        )
        headers = self._get_auth_headers()

        try:
            resp = requests.get(url, headers=headers)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning(f"Could not fetch {file_path}@{ref}: {e}")
            return None

    def post_review_comments(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[dict],
    ) -> None:
        """
        Post inline review comments on a Bitbucket PR.
        Falls back to general PR comments if inline fails.
        """
        import requests

        workspace, repo_slug = self._parse_repo(repo_full_name)
        url = (
            f"https://api.bitbucket.org/2.0/repositories/"
            f"{workspace}/{repo_slug}/pullrequests/{pr_number}/comments"
        )
        headers = self._get_auth_headers()
        headers["Content-Type"] = "application/json"

        posted = 0
        for c in comments:
            severity = c.get("severity", "INFO")
            body = c.get("body", "")
            file_path = c.get("file_path", "")
            line = int(c.get("line", 1))
            formatted = f"**[{severity}] DiffMaster Review**\n\n{body}"

            # Try inline comment first
            payload = {
                "content": {"raw": formatted},
                "inline": {
                    "to": line,
                    "path": file_path,
                },
            }

            try:
                resp = requests.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                posted += 1
                logger.info(f"  Posted {severity} on {file_path}:{line}")
            except Exception as e:
                logger.warning(f"  Inline comment failed on {file_path}:{line}: {e}")
                # Fallback: general PR comment
                try:
                    fallback_payload = {
                        "content": {"raw": f"`{file_path}:{line}`\n\n{formatted}"},
                    }
                    resp = requests.post(url, headers=headers, json=fallback_payload)
                    resp.raise_for_status()
                    posted += 1
                except Exception as e2:
                    logger.error(f"  General comment fallback also failed: {e2}")

        logger.info(f"Bitbucket: posted {posted}/{len(comments)} comments on PR #{pr_number}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_repo(self, repo_full_name: str) -> tuple[str, str]:
        """Parse 'workspace/repo_slug' into components."""
        parts = repo_full_name.split("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"Invalid Bitbucket repo format: '{repo_full_name}'. "
                "Expected 'workspace/repo_slug'."
            )
        return parts[0], parts[1]

    def _get_auth_headers(self) -> dict:
        """Return auth headers for Bitbucket REST API calls."""
        import base64

        if self._token:
            return {"Authorization": f"Bearer {self._token}"}

        # App password uses Basic auth
        creds = base64.b64encode(
            f"{self._username}:{self._app_password}".encode()
        ).decode()
        return {"Authorization": f"Basic {creds}"}

    @staticmethod
    def _split_diff_by_file(full_diff: str) -> dict[str, str]:
        """
        Split a full unified diff into per-file patches.
        Returns: { "path/to/file": "patch_content", ... }
        """
        patches: dict[str, str] = {}
        current_file = None
        current_lines: list[str] = []

        for line in full_diff.splitlines(keepends=True):
            if line.startswith("diff --git"):
                # Save previous file patch
                if current_file:
                    patches[current_file] = "".join(current_lines)
                # Extract new file path (b/path format)
                parts = line.split(" b/", 1)
                current_file = parts[1].strip() if len(parts) == 2 else None
                current_lines = [line]
            else:
                current_lines.append(line)

        # Save last file
        if current_file:
            patches[current_file] = "".join(current_lines)

        return patches
