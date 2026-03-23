"""
GitLab VCS client for DiffMaster.
Supports Merge Request review workflows via python-gitlab.

Mirrors the GitHubClient interface so the same review pipeline works
for both GitHub PRs and GitLab MRs.
"""

import logging
from typing import Optional

logger = logging.getLogger("diffmaster.gitlab")


class GitLabMRFile:
    """Represents a file changed in a GitLab MR (mirrors PyGithub File object)."""

    def __init__(self, filename: str, status: str, patch: str):
        self.filename = filename
        self.status = status
        self.patch = patch


class GitLabClient:
    """
    GitLab API client using python-gitlab.
    Interface-compatible with GitHubClient for the VCS-agnostic pipeline.

    Supports:
    - Merge Request file listing
    - Raw file content at a specific ref
    - Inline discussion comments on MR diffs
    - Policy file loading (.diffmaster.yml)
    """

    def __init__(
        self,
        token: Optional[str] = None,
        url: Optional[str] = None,
        default_project_id: Optional[int] = None,
    ):
        try:
            import gitlab
            from app.core.config import settings

            self._gl = gitlab.Gitlab(
                url=url or settings.GITLAB_URL,
                private_token=token or settings.GITLAB_TOKEN,
            )
            self._gl.auth()
            self._default_project_id = default_project_id
            logger.info(f"GitLab client authenticated to {url or settings.GITLAB_URL}")
        except ImportError:
            raise ImportError(
                "python-gitlab is required for GitLab support. "
                "Run: pip install python-gitlab"
            )
        except Exception as e:
            raise RuntimeError(f"GitLab authentication failed: {e}") from e

    # ------------------------------------------------------------------
    # Core interface (mirrors GitHubClient)
    # ------------------------------------------------------------------

    def get_pull_request(self, repo_full_name: str, pr_number: int):
        """Fetch a GitLab Merge Request object."""
        project = self._get_project(repo_full_name)
        return project.mergerequests.get(pr_number)

    def get_pr_files(self, repo_full_name: str, pr_number: int) -> list[GitLabMRFile]:
        """Return list of files changed in a Merge Request."""
        project = self._get_project(repo_full_name)
        mr = project.mergerequests.get(pr_number)
        changes = mr.changes()

        files = []
        for change in changes.get("changes", []):
            new_path = change.get("new_path", "")
            old_path = change.get("old_path", "")
            diff = change.get("diff", "")
            deleted = change.get("deleted_file", False)
            new_file = change.get("new_file", False)

            if new_file:
                status = "added"
            elif deleted:
                status = "deleted"
            else:
                status = "modified"

            files.append(GitLabMRFile(
                filename=new_path or old_path,
                status=status,
                patch=diff,
            ))

        return files

    def get_file_content(
        self, repo_full_name: str, file_path: str, ref: str
    ) -> Optional[str]:
        """Fetch raw file content at a specific commit SHA or branch ref."""
        try:
            project = self._get_project(repo_full_name)
            f = project.files.get(file_path=file_path, ref=ref)
            return f.decode().decode("utf-8")
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
        Post inline review comments on a GitLab MR.
        Falls back to general MR notes if inline discussion fails.
        """
        project = self._get_project(repo_full_name)
        mr = project.mergerequests.get(pr_number)
        diff_refs = mr.diff_refs or {}

        posted = 0
        for c in comments:
            severity = c.get("severity", "INFO")
            body = c.get("body", "")
            file_path = c.get("file_path", "")
            line = int(c.get("line", 1))
            formatted = f"**[{severity}] DiffMaster Review**\n\n{body}"

            try:
                mr.discussions.create({
                    "body": formatted,
                    "position": {
                        "base_sha": diff_refs.get("base_sha", commit_sha),
                        "start_sha": diff_refs.get("start_sha", commit_sha),
                        "head_sha": commit_sha,
                        "position_type": "text",
                        "new_path": file_path,
                        "new_line": line,
                    },
                })
                posted += 1
                logger.info(f"  ✅ Posted {severity} on {file_path}:{line}")
            except Exception as e:
                logger.warning(f"  ⚠️ Inline comment failed on {file_path}:{line}: {e}")
                # Fallback: post as a general MR note
                try:
                    mr.notes.create({"body": f"**`{file_path}:{line}`**\n\n{formatted}"})
                    posted += 1
                except Exception as e2:
                    logger.error(f"  ❌ MR note fallback also failed: {e2}")

        logger.info(f"GitLab: posted {posted}/{len(comments)} comments on MR !{pr_number}")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_project(self, repo_full_name: str):
        """Resolve project by ID (preferred) or namespace/path."""
        if self._default_project_id:
            return self._gl.projects.get(self._default_project_id)
        return self._gl.projects.get(repo_full_name)
