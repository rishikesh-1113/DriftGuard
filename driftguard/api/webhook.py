"""
FastAPI webhook endpoint for DriftGuard.
Receives GitHub App webhook events and triggers the agent review.
Supports multi-tenant operation via GitHub App installation tokens.
"""

import os
import hmac
import hashlib
import json
import logging
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from dotenv import load_dotenv

from driftguard.api.github import get_pr_context, get_file_content, post_pr_comment
from driftguard.api.github_app import get_installation_token
from driftguard.agent.graph import agent

load_dotenv()

app = FastAPI(title="DriftGuard", description="Agentic PR reviewer for K8s/Docker configs")

# Findings from a review sit here, waiting for a human /approve, before
# they're written to Qdrant memory. Keyed by "repo_name#pr_number".
# NOTE: in-memory only — fine for a single-process demo, would need a real
# store (DB/Redis) for production/multi-worker deployments.
_pending_reviews: dict[str, list[dict]] = {}


def verify_github_signature(payload: bytes, signature: str) -> bool:
    """Verify the webhook came from GitHub using the webhook secret."""
    if not payload:
        return False
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        return True
    if not signature:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def run_review(repo_name: str, pr_number: int, installation_id: int):
    """
    Background task: runs the agent on all changed manifest files in a PR
    and posts findings as a PR comment. Uses an installation-scoped token
    so this works for any repo that has installed the GitHub App.
    """
    try:
        token = get_installation_token(installation_id)
        pr_context = get_pr_context(repo_name, pr_number, token=token)

        if not pr_context.files:
            post_pr_comment(repo_name, pr_number,
                "**DriftGuard:** No Kubernetes/Docker files changed in this PR.",
                token=token)
            return

        all_comments = []
        review_key = f"{repo_name}#{pr_number}"
        pending_for_this_pr = []

        for pr_file in pr_context.files:
            # fetch full file content
            try:
                content = get_file_content(pr_file.raw_url, token=token)
            except Exception:
                content = ""

            # run agent
            result = agent.invoke({
    "file_path": pr_file.filename,
    "file_content": content,
    "diff": pr_file.patch,
    "repo_name": repo_name,       # ADD THIS LINE — repo_name is already a variable in this function
})

            if result.get("pr_comment"):
                all_comments.append(result["pr_comment"])

            for finding in result.get("pending_approval_findings", []):
                pending_for_this_pr.append({**finding, "file_path": pr_file.filename})

        # stash for handle_approval() to pick up later — nothing is written
        # to Qdrant yet, no matter how confident the LLM was
        if pending_for_this_pr:
            _pending_reviews[review_key] = pending_for_this_pr

        # post combined comment
        if all_comments:
            final_comment = "\n\n---\n\n".join(all_comments)
            final_comment += "\n\n---\n> To acknowledge this review, comment `/approve` on this PR."
            post_pr_comment(repo_name, pr_number, final_comment, token=token)

    except Exception as e:
        try:
            token = get_installation_token(installation_id)
            post_pr_comment(repo_name, pr_number,
                f"**DriftGuard Error:** Review failed — `{str(e)}`",
                token=token)
        except Exception:
            print(f"[run_review] failed and could not report error: {e}")


def handle_approval(repo_name: str, pr_number: int, commenter: str, installation_id: int):
    """
    Called when someone comments /approve on a PR.
    This is now the ONLY place findings get written to Qdrant memory —
    confidence alone (in record()) no longer triggers a write.
    """
    from driftguard.memory.store import store_approved_finding

    print(f"[approval] {commenter} approved DriftGuard review on {repo_name}#{pr_number}")

    review_key = f"{repo_name}#{pr_number}"
    pending = _pending_reviews.pop(review_key, [])

    stored_count = 0
    for finding in pending:
        try:
            store_approved_finding(
                rule=finding.get("rule", ""),
                severity=finding.get("severity", ""),
                message=finding.get("message", ""),
                reasoning=finding.get("reasoning", ""),
                approved_fix=finding.get("suggested_fix", ""),
                file_path=finding.get("file_path", ""),
                pr_number=pr_number,
                repo_name=repo_name,
            )
            stored_count += 1
        except Exception:
            logging.warning("[handle_approval] memory store failed for finding: %s", finding.get("rule", ""))

    try:
        token = get_installation_token(installation_id)
        if stored_count:
            ack = f"Approved by @{commenter} — {stored_count} finding(s) saved to memory for future reviews."
        else:
            ack = f"Approval acknowledged by @{commenter}. No pending findings were found to save (review may have already been approved, or had no high-confidence findings)."
        post_pr_comment(repo_name, pr_number, ack, token=token)
    except Exception as e:
        print(f"[handle_approval] failed to post comment: {e}")


@app.post("/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """Receives GitHub webhook events: pull_request and issue_comment."""
    payload_bytes = await request.body()

    # verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_github_signature(payload_bytes, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event = request.headers.get("X-GitHub-Event", "")
    payload = json.loads(payload_bytes)

    # every GitHub App event includes an "installation" object with its id
    installation = payload.get("installation", {})
    installation_id = installation.get("id")

    # --- handle /approve comments ---
    if event == "issue_comment":
        action = payload.get("action", "")
        comment_body = payload.get("comment", {}).get("body", "").strip().lower()
        is_pr_comment = "pull_request" in payload.get("issue", {})

        if action == "created" and is_pr_comment and comment_body == "/approve" and installation_id:
            repo_name = payload["repository"]["full_name"]
            pr_number = payload["issue"]["number"]
            commenter = payload["comment"]["user"]["login"]
            association = payload["comment"].get("author_association", "NONE")

            if association not in ("OWNER", "MEMBER", "COLLABORATOR"):
                token = get_installation_token(installation_id)
                post_pr_comment(repo_name, pr_number,
                    "@" + commenter + " you dont have permission to approve DriftGuard reviews on this repo.",
                    token=token)
                return {"status": "rejected", "reason": "insufficient permission"}

            background_tasks.add_task(handle_approval, repo_name, pr_number, commenter, installation_id)
            return {"status": "approval received", "pr": pr_number}

        return {"status": "ignored", "event": event, "action": action}

    # --- handle PR opened/updated ---
    if event != "pull_request":
        return {"status": "ignored", "event": event}

    action = payload.get("action", "")

    # only trigger on opened or new commits pushed
    if action not in ("opened", "synchronize"):
        return {"status": "ignored", "action": action}

    if not installation_id:
        return {"status": "ignored", "reason": "no installation id found"}

    repo_name = payload["repository"]["full_name"]
    pr_number = payload["pull_request"]["number"]

    # run review in background so webhook returns immediately
    background_tasks.add_task(run_review, repo_name, pr_number, installation_id)

    return {"status": "review started", "pr": pr_number}


@app.get("/health")
async def health():
    return {"status": "ok"}