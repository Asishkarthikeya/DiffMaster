"""Abstract VCS integration interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class DiffHunk:
    file_path: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    content: str
    header: str = ""
    is_new_file: bool = False
    is_deleted_file: bool = False
    is_binary: bool = False


@dataclass
class PullRequestInfo:
    number: int
    title: str
    author: str
    head_sha: str
    base_sha: str
    base_branch: str
    head_branch: str
    body: str = ""
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0


@dataclass
class FileContent:
    path: str
    content: str
    language: str | None = None
    size: int = 0


@dataclass
class RepoMetadata:
    full_name: str
    owner: str
    name: str
    default_branch: str
    language: str | None = None
    frameworks: list[str] = field(default_factory=list)


@dataclass
class ReviewCommentPayload:
    file_path: str
    line: int
    body: str
    side: str = "RIGHT"


class VCSIntegration(ABC):
    """Abstract base class for VCS platform integrations."""

    @abstractmethod
    async def get_pull_request(self, repo_full_name: str, pr_number: int) -> PullRequestInfo:
        ...

    @abstractmethod
    async def get_diff(self, repo_full_name: str, pr_number: int) -> list[DiffHunk]:
        ...

    @abstractmethod
    async def get_file_content(
        self, repo_full_name: str, path: str, ref: str
    ) -> FileContent:
        ...

    @abstractmethod
    async def get_repo_metadata(self, repo_full_name: str) -> RepoMetadata:
        ...

    @abstractmethod
    async def post_review_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        comments: list[ReviewCommentPayload],
    ) -> list[str]:
        ...

    @abstractmethod
    async def post_review_summary(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str,
    ) -> str:
        ...
