"""
CI entry point for GitHub Actions.
Called by .github/workflows/review.yml on every PR.
Reads PR context, runs agent, posts comment.

Since this runs as a one-shot GitHub Actions job, there's no in-memory state
that survives until someone comments /approve later (that's a separate job,
possibly minutes or days after, on a different runner). So pending findings
are embedded as a hidden, base64-encoded HTML comment inside the posted PR
comment — GitHub's own comment thread becomes the durable storage.
See ci_approve.py for the other half of this flow.
"""

import os
import json
import base64
from dotenv import load_dotenv
from driftguard.api.github import get_pr_context, get_file_content, post_pr_comment
from driftguard.agent.graph import agent

load_dotenv()

PENDING_MARKER_PREFIX = "driftguard-pending:"


def _build_pending_marker(findings: list) -> str:
    """Hidden HTML comment carrying pending findings — invisible when rendered,
    readable via the GitHub API by ci_approve.py."""
    encoded = base64.b64encode(json.dumps(findings).encode()).decode()
    return f"<!-- {PENDING_MARKER_PREFIX}{encoded} -->"


def main():
    repo_name = os.getenv("GITHUB_REPO")
    pr_number = int(os.getenv("PR_NUMBER", "0"))

    if not repo_name or not pr_number:
        print("GITHUB_REPO and PR_NUMBER must be set.")
        return

    print(f"DriftGuard reviewing PR #{pr_number} in {repo_name}")

    pr_context = get_pr_context(repo_name, pr_number)

    if not pr_context.files:
        print("No K8s/Docker files changed. Skipping.")
        return

    all_comments = []
    all_pending = []

    for pr_file in pr_context.files:
        print(f"  Reviewing: {pr_file.filename}")
        try:
            content = get_file_content(pr_file.raw_url)
        except Exception as e:
            print(f"  Could not fetch content: {e}")
            content = ""

        result = agent.invoke({
    "file_path": pr_file.filename,
    "file_content": content,
    "diff": pr_file.patch,
    "repo_name": repo_name,       # ADD THIS LINE — already a variable here too
})

        if result.get("pr_comment"):
            all_comments.append(result["pr_comment"])

        for finding in result.get("pending_approval_findings", []):
            all_pending.append({**finding, "file_path": pr_file.filename})

    if all_comments:
        final_comment = "\n\n---\n\n".join(all_comments)
        final_comment += "\n\n---\n> To acknowledge this review, comment `/approve` on this PR."
        if all_pending:
            # nothing is saved to memory yet — this marker just carries the
            # candidate findings until a human approves them
            final_comment += "\n\n" + _build_pending_marker(all_pending)
        post_pr_comment(repo_name, pr_number, final_comment)
        print("Review posted successfully.")
    else:
        print("No findings.")


if __name__ == "__main__":
    main()