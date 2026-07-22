"""
GitHub API client for DriftGuard.
Handles reading PR diffs and posting review comments.
Read PR contents + write PR comments — nothing else.

Supports two auth modes:
- Personal token (GITHUB_TOKEN) — single-repo/testing mode
- Installation token (passed in per-call) — multi-tenant GitHub App mode
"""

import os
import requests
from dataclasses import dataclass, field
from typing import List, Optional
from github import Github, Auth
from dotenv import load_dotenv

load_dotenv()


def get_github_client(token: Optional[str] = None) -> Github:
    """
    Returns an authenticated GitHub client.
    If a token is passed explicitly (e.g. an installation token), use that.
    Otherwise fall back to the personal GITHUB_TOKEN from .env.
    """
    if not token:
        token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise ValueError("No GitHub token available — set GITHUB_TOKEN or pass an installation token")
    return Github(auth=Auth.Token(token))


@dataclass
class PRFile:
    filename: str
    status: str        # added, modified, removed
    patch: str         # the diff hunk
    raw_url: str       # url to fetch full file content


@dataclass
class PRContext:
    pr_number: int
    title: str
    body: str
    files: List[PRFile] = field(default_factory=list)


def get_pr_context(repo_name: str, pr_number: int, token: Optional[str] = None) -> PRContext:
    """Fetch PR metadata and changed files with diffs."""
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    files = [
        PRFile(
            filename=f.filename,
            status=f.status,
            patch=f.patch or "",
            raw_url=f.raw_url,
        )
        for f in pr.get_files()
        if f.filename.endswith((".yaml", ".yml")) or "Dockerfile" in f.filename
    ]

    return PRContext(
        pr_number=pr_number,
        title=pr.title,
        body=pr.body or "",
        files=files,
    )


def get_file_content(raw_url: str, token: Optional[str] = None) -> str:
    """Fetch full file content from GitHub raw URL."""
    if not token:
        token = os.getenv("GITHUB_TOKEN")
    resp = requests.get(
        raw_url,
        headers={"Authorization": f"token {token}"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.text


def post_pr_comment(repo_name: str, pr_number: int, comment: str, token: Optional[str] = None) -> None:
    """Post a review comment on a PR."""
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    pr.create_issue_comment(comment)


def get_approval_status(repo_name: str, pr_number: int, token: Optional[str] = None) -> bool:
    """
    Check if a human has approved the DriftGuard review by commenting '/approve'.
    This is the human-in-the-loop gate.
    """
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)

    for comment in pr.get_issue_comments():
        if comment.body.strip() == "/approve":
            return True
    return False


def list_pr_comments(repo_name: str, pr_number: int, token: Optional[str] = None) -> List[dict]:
    """
    Return every comment on a PR as plain dicts: {"body": ..., "user": ...}.
    Used by the GitHub-Actions-based approval flow (ci_approve.py) to find
    DriftGuard's own review comments, since a CI job has no persistent memory
    between runs — GitHub's own comment history is the only durable state.
    """
    gh = get_github_client(token)
    repo = gh.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    return [
        {"body": c.body or "", "user": c.user.login if c.user else ""}
        for c in pr.get_issue_comments()
    ]