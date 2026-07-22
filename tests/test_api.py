"""
Tests for Phase 4 GitHub integration.
All GitHub API calls are mocked — no real API calls made.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from driftguard.api.webhook import app, verify_github_signature
from driftguard.api.github import get_approval_status

client = TestClient(app)


# --- webhook endpoint ---

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_ignores_non_pr_events():
    with patch("driftguard.api.webhook.os.getenv", return_value=""):
        response = client.post(
            "/webhook",
            json={},
            headers={"X-GitHub-Event": "push"}
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_ignores_non_open_actions():
    with patch("driftguard.api.webhook.os.getenv", return_value=""):
        response = client.post(
            "/webhook",
            content=b'{"action": "closed", "repository": {"full_name": "user/repo"}, "pull_request": {"number": 1}}',
            headers={"X-GitHub-Event": "pull_request", "Content-Type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_webhook_accepts_opened_pr():
    payload = b'{"action": "opened", "repository": {"full_name": "user/repo"}, "pull_request": {"number": 42}, "installation": {"id": 12345}}'
    with patch("driftguard.api.webhook.run_review"), \
         patch("driftguard.api.webhook.os.getenv", return_value=""):
        response = client.post(
            "/webhook",
            content=payload,
            headers={"X-GitHub-Event": "pull_request", "Content-Type": "application/json"}
        )
    assert response.status_code == 200
    assert response.json()["status"] == "review started"
    assert response.json()["pr"] == 42


# --- signature verification ---

def test_verify_signature_no_secret():
    # when no secret set, verification is skipped
    with patch("driftguard.api.webhook.os.getenv", return_value=""):
        assert verify_github_signature(b"payload", "") is True


# --- approval gate ---

def test_approval_status_approved():
    mock_comment = MagicMock()
    mock_comment.body = "/approve"
    mock_pr = MagicMock()
    mock_pr.get_issue_comments.return_value = [mock_comment]
    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo
    with patch("driftguard.api.github.get_github_client", return_value=mock_gh):
        result = get_approval_status("user/repo", 1)
        assert result is True


def test_approval_status_not_approved():
    mock_comment = MagicMock()
    mock_comment.body = "looks good to me"
    mock_pr = MagicMock()
    mock_pr.get_issue_comments.return_value = [mock_comment]
    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    mock_gh = MagicMock()
    mock_gh.get_repo.return_value = mock_repo
    with patch("driftguard.api.github.get_github_client", return_value=mock_gh):
        result = get_approval_status("user/repo", 1)
        assert result is False
