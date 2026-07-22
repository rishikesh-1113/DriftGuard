"""
Local end-to-end test for the ci_review.py -> ci_approve.py flow.
Run this BEFORE pushing anything to GitHub.

Uses your REAL .env (real Gemini calls, real Qdrant writes) so you see
actual behavior — but fakes only the GitHub-specific calls (post_pr_comment,
list_pr_comments) with a Python list standing in for a PR's comment thread.
That means:
  - You'll see a real AI-generated review of a real bad manifest
  - You'll see a real write land in your actual Qdrant collection
  - You'll confirm that write only happens on the "approve" step, not before

Usage:
  cd DriftGuard
  python scripts/local_e2e_test.py
  (or wherever you keep it — just make sure it can import driftguard.*)
"""

import os
import sys
from unittest.mock import patch, MagicMock

# make sure the project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from driftguard import ci_review, ci_approve

REPO_NAME = "local/test-repo"
PR_NUMBER = 999
COMMENTER = "rishikesh"

# pick any file under samples/bad-manifests — change this if you want to test a different one
MANIFEST_PATH = "samples/bad-manifests/deployment.yaml"

os.environ["GITHUB_REPO"] = REPO_NAME
os.environ["PR_NUMBER"] = str(PR_NUMBER)
os.environ["COMMENTER"] = COMMENTER

# --- fake "GitHub" comment thread, shared across both steps ---
fake_comment_thread = []


def fake_post_pr_comment(repo_name, pr_number, comment, token=None):
    print(f"\n[FAKE GITHUB] Comment posted to {repo_name}#{pr_number}:\n{'-'*60}")
    print(comment)
    print("-" * 60)
    fake_comment_thread.append({"body": comment, "user": "driftguard-bot"})


def fake_list_pr_comments(repo_name, pr_number, token=None):
    return list(fake_comment_thread)


def fake_get_pr_context(repo_name, pr_number, token=None):
    with open(MANIFEST_PATH, "r") as f:
        content = f.read()
    fake_file = MagicMock()
    fake_file.filename = MANIFEST_PATH
    fake_file.raw_url = "unused"
    fake_file.patch = "unused"
    ctx = MagicMock()
    ctx.files = [fake_file]
    return ctx


def fake_get_file_content(raw_url, token=None):
    with open(MANIFEST_PATH, "r") as f:
        return f.read()


print("=" * 70)
print("STEP 1: Simulating the 'review' job (ci_review.py)")
print("This makes a REAL Gemini call and evaluates a REAL manifest.")
print("=" * 70)

with patch.object(ci_review, "get_pr_context", side_effect=fake_get_pr_context), \
     patch.object(ci_review, "get_file_content", side_effect=fake_get_file_content), \
     patch.object(ci_review, "post_pr_comment", side_effect=fake_post_pr_comment):
    ci_review.main()

if not fake_comment_thread:
    print("\nNo comment was posted — likely no findings were returned. Stopping here.")
    sys.exit(0)

has_marker = "driftguard-pending:" in fake_comment_thread[0]["body"]
print(f"\n>> Hidden pending-findings marker present in comment: {has_marker}")
print(">> At this point, check your Qdrant dashboard/collection — nothing new should be there yet.")

input("\nPress Enter once you've confirmed nothing is in Qdrant yet, to continue to the approve step...")

print("\n" + "=" * 70)
print("STEP 2: Simulating the 'approve' job (ci_approve.py) — someone comments /approve")
print("This makes a REAL Qdrant write.")
print("=" * 70)

with patch.object(ci_approve, "list_pr_comments", side_effect=fake_list_pr_comments), \
     patch.object(ci_approve, "post_pr_comment", side_effect=fake_post_pr_comment):
    ci_approve.main()

print("\n>> Now check your Qdrant collection again — you should see 1 new point.")
print("\n" + "=" * 70)
print("STEP 3: Simulating a duplicate /approve (should NOT write again)")
print("=" * 70)

with patch.object(ci_approve, "list_pr_comments", side_effect=fake_list_pr_comments), \
     patch.object(ci_approve, "post_pr_comment", side_effect=fake_post_pr_comment):
    ci_approve.main()

print("\n>> Qdrant count should be unchanged from Step 2 — confirm no duplicate was added.")
print("\nDone. If both checks above matched what you expected, the fix is confirmed working end to end.")