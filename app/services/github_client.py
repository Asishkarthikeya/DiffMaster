from github import Github, Auth
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class GitHubClient:
    """GitHub API client for fetching PR data and posting review comments."""

    def __init__(self):
        auth = Auth.Token(settings.GITHUB_TOKEN)
        self.gh = Github(auth=auth)

    def get_repo(self, repo_full_name: str):
        return self.gh.get_repo(repo_full_name)

    def get_pull_request(self, repo_full_name: str, pr_number: int):
        repo = self.get_repo(repo_full_name)
        return repo.get_pull(pr_number)

    def get_pr_files(self, repo_full_name: str, pr_number: int):
        pr = self.get_pull_request(repo_full_name, pr_number)
        return pr.get_files()

    def get_file_content(self, repo_full_name: str, file_path: str, ref: str) -> str:
        """Fetch raw file content from a specific commit SHA."""
        try:
            repo = self.get_repo(repo_full_name)
            file_obj = repo.get_contents(file_path, ref=ref)
            return file_obj.decoded_content.decode("utf-8")
        except Exception as e:
            logger.warning(f"Could not fetch {file_path}@{ref}: {e}")
            return ""

    def post_review_comments(self, repo_full_name: str, pr_number: int, commit_sha: str, comments: list[dict]):
        """Post multiple review comments to a PR in a single review."""
        pr = self.get_pull_request(repo_full_name, pr_number)

        if not comments:
            logger.info("No review comments to post.")
            return

        # Build the review comments list
        review_comments = []
        for c in comments:
            review_comments.append({
                "path": c["file_path"],
                "line": int(c["line"]),
                "side": "RIGHT",
                "body": f"**[{c['severity']}] DiffMaster Review**\n\n{c['body']}"
            })

        try:
            pr.create_review(
                commit=pr.get_commits().reversed[0] if pr.get_commits().totalCount > 0 else None,
                body="🤖 **DiffMaster Automated Review**",
                event="COMMENT",
                comments=review_comments
            )
            logger.info(f"Posted {len(review_comments)} review comments to PR #{pr_number}")
        except Exception as e:
            logger.error(f"Failed to post review to PR #{pr_number}: {e}")
            # Fallback: post individual comments
            for c in comments:
                try:
                    pr.create_review_comment(
                        body=f"**[{c['severity']}] DiffMaster Review**\n\n{c['body']}",
                        commit_id=commit_sha,
                        path=c["file_path"],
                        line=int(c["line"]),
                        side="RIGHT"
                    )
                except Exception as inner_e:
                    logger.error(f"Failed to post comment on {c['file_path']}:{c['line']}: {inner_e}")

    def post_pr_summary(self, repo_full_name: str, pr_number: int, summary_markdown: str):
        """Post a top-level PR review summary."""
        if not summary_markdown:
            return
        try:
            # Post an issue comment so it appears at the bottom of the PR conversation
            issue = self.get_repo(repo_full_name).get_issue(pr_number)
            issue.create_comment(summary_markdown)
            logger.info(f"Posted top-level review summary to PR #{pr_number}")
        except Exception as e:
            logger.error(f"Failed to post top-level review summary: {e}")

    def update_pr_description(self, repo_full_name: str, pr_number: int, description_markdown: str):
        """Append an AI-generated summary to the PR description body."""
        pr = self.get_pull_request(repo_full_name, pr_number)
        current_body = pr.body or ""
        
        if "🤖 DiffMaster PR Summary" in current_body:
            logger.info("PR Summary already exists. Skipping description update.")
            return

        new_body = current_body + "\n\n---\n\n" + description_markdown
        pr.edit(body=new_body)
        logger.info(f"Updated PR #{pr_number} description.")

    def reply_to_comment(self, repo_full_name: str, pr_number: int, reply_markdown: str):
        """Reply to a user's ChatOps comment."""
        if not reply_markdown:
            return
        try:
            issue = self.get_repo(repo_full_name).get_issue(pr_number)
            issue.create_comment(reply_markdown)
            logger.info(f"Posted ChatOps reply to PR #{pr_number}")
        except Exception as e:
            logger.error(f"Failed to post ChatOps reply: {e}")
