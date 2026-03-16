"""Schemas for VCS webhook payloads."""

from pydantic import BaseModel, Field


class GitHubUser(BaseModel):
    login: str
    id: int


class GitHubRef(BaseModel):
    ref: str
    sha: str
    label: str | None = None


class GitHubRepository(BaseModel):
    id: int
    name: str
    full_name: str
    owner: GitHubUser
    default_branch: str = "main"
    language: str | None = None


class GitHubPullRequest(BaseModel):
    number: int
    title: str
    state: str
    user: GitHubUser
    head: GitHubRef
    base: GitHubRef
    body: str | None = None
    additions: int = 0
    deletions: int = 0
    changed_files: int = 0


class GitHubWebhookPayload(BaseModel):
    action: str
    pull_request: GitHubPullRequest
    repository: GitHubRepository
    sender: GitHubUser


class GitLabProject(BaseModel):
    id: int
    name: str
    path_with_namespace: str
    default_branch: str = "main"


class GitLabMergeRequestAttrs(BaseModel):
    iid: int
    title: str
    state: str
    author_id: int
    source_branch: str
    target_branch: str
    last_commit: dict = Field(default_factory=dict)


class GitLabWebhookPayload(BaseModel):
    object_kind: str
    event_type: str
    project: GitLabProject
    object_attributes: GitLabMergeRequestAttrs


class WebhookResponse(BaseModel):
    status: str
    review_id: str | None = None
    message: str
