"""
CI entry point for handling /approve comments via GitHub Actions.
Called by .github/workflows/review.yml's `approve` job whenever someone
comments /approve on a PR.

This is the CI-only counterpart to handle_approval() in webhook.py. Since a
GitHub Actions job starts fresh every time with no shared memory, it can't
read an in-process "pending reviews" dict like the FastAPI server can.
Instead it re-reads the PR's own comment thread, finds the hidden marker(s)
ci_review.py embedded, decodes the pending findings, and only THEN writes
them to Qdrant — the same "storage only happens after a real human comments
/approve" rule, just implemented against GitHub as the state store instead
of an in-memory dict.
"""

import os
import json
import base64
import logging
from dotenv import load_dotenv

from driftguard.api.github import list_pr_comments, post_pr_comment
from driftguard.ci_review import PENDING_MARKER_PREFIX

load_dotenv()

ALREADY_APPROVED_MARKER = "<!-- driftguard-approved -->"


def _extract_pending_findings(comments: list) -> list:
    """Pull every pending-findings marker out of DriftGuard's own comments
    and merge them into one list. Ignores anything that isn't a valid marker."""
    all_findings = []
    for comment in comments:
        body = comment.get("body", "")
        idx = body.find(PENDING_MARKER_PREFIX)
        if idx == -1:
            continue
        start = idx + len(PENDING_MARKER_PREFIX)
        end = body.find("-->", start)
        encoded = body[start:end].strip() if end != -1 else body[start:].strip()
        try:
            findings = json.loads(base64.b64decode(encoded).decode())
            all_findings.extend(findings)
        except Exception as e:
            logging.warning("[ci_approve] failed to decode a pending marker: %s", e)
    return all_findings


def _already_approved(comments: list) -> bool:
    return any(ALREADY_APPROVED_MARKER in c.get("body", "") for c in comments)


def main():
    from driftguard.memory.store import store_approved_finding

    repo_name = os.getenv("GITHUB_REPO")
    pr_number = int(os.getenv("PR_NUMBER", "0"))
    commenter = os.getenv("COMMENTER", "someone")

    if not repo_name or not pr_number:
        print("GITHUB_REPO and PR_NUMBER must be set.")
        return

    association = os.getenv("COMMENTER_ASSOCIATION", "NONE")
    if association not in ("OWNER", "MEMBER", "COLLABORATOR"):
        print("Rejected /approve from @" + commenter + " (association: " + association + ") - not authorized.")
        post_pr_comment(
            repo_name, pr_number,
            "@" + commenter + " you dont have permission to approve DriftGuard reviews on this repo.",
        )
        return

    comments = list_pr_comments(repo_name, pr_number)

    if _already_approved(comments):
        print(f"PR #{pr_number} was already approved before — skipping duplicate save.")
        post_pr_comment(
            repo_name, pr_number,
            f"@{commenter} this review was already approved earlier — nothing new to save.",
        )
        return

    pending = _extract_pending_findings(comments)

    if not pending:
        print("No pending findings found to save.")
        post_pr_comment(
            repo_name, pr_number,
            f"Approval acknowledged by @{commenter}. No pending high-confidence findings were found to save.\n\n{ALREADY_APPROVED_MARKER}",
        )
        return

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
        except Exception as e:
            logging.warning("[ci_approve] memory store failed for finding: %s (%s)", finding.get("rule", ""), e)

    print(f"Stored {stored_count} approved finding(s) to memory.")
    post_pr_comment(
        repo_name, pr_number,
        f"Approved by @{commenter} — {stored_count} finding(s) saved to memory for future reviews.\n\n{ALREADY_APPROVED_MARKER}",
    )


if __name__ == "__main__":
    main()