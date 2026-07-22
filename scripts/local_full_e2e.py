"""
ONE-SHOT full local validation of DriftGuard — everything except real GitHub.
Uses your REAL Gemini + Qdrant. Fakes only GitHub network calls.

Covers:
  PART A — CI path (ci_review.py -> ci_approve.py) across ALL sample manifests
  PART B — Webhook path (webhook.py, via FastAPI TestClient) — the actual
           HTTP routes GitHub would hit, simulated locally
  PART C — Memory RECALL loop — proves the agent actually remembers and
           surfaces a past approved finding on a later review (the core
           "learns team conventions" pitch), not just that it can write

Uses a dedicated repo_name ("local/full-e2e-test") and PR numbers so it never
collides with your real data or earlier test runs. Nothing here touches
GitHub — safe to run before ever pushing/committing.

Usage:
  cd DriftGuard
  python scripts/local_full_e2e.py
"""

import os
import sys
import glob
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO_NAME = "local/full-e2e-test"

os.environ["GITHUB_WEBHOOK_SECRET"] = ""  # skip signature check for local test

def line(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


# ---------------------------------------------------------------------------
# PART A — CI path across every sample manifest
# ---------------------------------------------------------------------------
line("PART A: CI path (ci_review.py -> ci_approve.py) across all sample manifests")

from driftguard import ci_review, ci_approve

manifest_files = sorted(glob.glob("samples/bad-manifests/*"))
print(f"Found {len(manifest_files)} sample file(s): {manifest_files}")

PR_NUMBER_A = 100001
os.environ["GITHUB_REPO"] = REPO_NAME
os.environ["PR_NUMBER"] = str(PR_NUMBER_A)
os.environ["COMMENTER"] = "rishikesh"

comment_thread_a = []

def post_a(repo_name, pr_number, comment, token=None):
    comment_thread_a.append({"body": comment, "user": "driftguard-bot"})

def list_a(repo_name, pr_number, token=None):
    return list(comment_thread_a)

def get_pr_context_a(repo_name, pr_number, token=None):
    files = []
    for path in manifest_files:
        f = MagicMock()
        f.filename = path
        f.raw_url = "unused"
        f.patch = "unused"
        files.append(f)
    ctx = MagicMock()
    ctx.files = files
    return ctx

def get_file_content_a(raw_url, token=None):
    # raw_url isn't meaningful here since we mocked get_pr_context; instead
    # nodes.py's collect() reads file_path directly off disk, so this is
    # only a fallback and won't normally be hit
    return ""

with patch.object(ci_review, "get_pr_context", side_effect=get_pr_context_a), \
     patch.object(ci_review, "get_file_content", side_effect=get_file_content_a), \
     patch.object(ci_review, "post_pr_comment", side_effect=post_a):
    ci_review.main()

if comment_thread_a:
    print(f"\nReview comment posted ({len(comment_thread_a[0]['body'])} chars).")
    print("Contains pending marker:", "driftguard-pending:" in comment_thread_a[0]["body"])
else:
    print("No comment posted — check for errors above.")

with patch.object(ci_approve, "list_pr_comments", side_effect=list_a), \
     patch.object(ci_approve, "post_pr_comment", side_effect=post_a):
    print("\n-- approving --")
    ci_approve.main()
    print("\n-- approving again (should be a no-op) --")
    ci_approve.main()

print(f"\n>> Check Qdrant now: expect new points with repo_name='{REPO_NAME}', pr_number={PR_NUMBER_A}")
input("Press Enter to continue to Part B (webhook path)...")


# ---------------------------------------------------------------------------
# PART B — Webhook path via FastAPI TestClient
# ---------------------------------------------------------------------------
line("PART B: Webhook path (webhook.py) via FastAPI TestClient")

from fastapi.testclient import TestClient
from driftguard.api import webhook as wh

test_client = TestClient(wh.app)

PR_NUMBER_B = 100002
INSTALLATION_ID = 999999

fake_file_b = MagicMock()
fake_file_b.filename = manifest_files[0] if manifest_files else "samples/bad-manifests/deployment.yaml"
fake_file_b.raw_url = "unused"
fake_file_b.patch = "unused"

def get_pr_context_b(repo_name, pr_number, token=None):
    ctx = MagicMock()
    ctx.files = [fake_file_b]
    return ctx

def get_file_content_b(raw_url, token=None):
    with open(fake_file_b.filename, "r") as f:
        return f.read()

with patch.object(wh, "get_installation_token", return_value="fake-token"), \
     patch.object(wh, "get_pr_context", side_effect=get_pr_context_b), \
     patch.object(wh, "get_file_content", side_effect=get_file_content_b), \
     patch.object(wh, "post_pr_comment") as mock_post_b:

    print("Simulating GitHub sending a 'pull_request opened' webhook...")
    resp = test_client.post(
        "/webhook",
        json={
            "action": "opened",
            "repository": {"full_name": REPO_NAME},
            "pull_request": {"number": PR_NUMBER_B},
            "installation": {"id": INSTALLATION_ID},
        },
        headers={"X-GitHub-Event": "pull_request"},
    )
    print("Response:", resp.status_code, resp.json())

    review_key = f"{REPO_NAME}#{PR_NUMBER_B}"
    print("Pending review parked:", review_key in wh._pending_reviews)
    print(">> Check Qdrant: should be UNCHANGED so far (no new points from this PR yet)")

    print("\nSimulating someone commenting /approve...")
    resp2 = test_client.post(
        "/webhook",
        json={
            "action": "created",
            "issue": {"number": PR_NUMBER_B, "pull_request": {}},
            "comment": {"body": "/approve", "user": {"login": "rishikesh"}},
            "repository": {"full_name": REPO_NAME},
            "installation": {"id": INSTALLATION_ID},
        },
        headers={"X-GitHub-Event": "issue_comment"},
    )
    print("Response:", resp2.status_code, resp2.json())
    print("Pending review cleared:", review_key not in wh._pending_reviews)
    print(f">> Check Qdrant now: expect new point(s) with repo_name='{REPO_NAME}', pr_number={PR_NUMBER_B}")

input("Press Enter to continue to Part C (memory recall loop)...")


# ---------------------------------------------------------------------------
# PART C — Memory recall: does the agent actually remember?
# ---------------------------------------------------------------------------
line("PART C: Memory RECALL loop — does a later review on the same repo see the past finding?")

from driftguard.memory.recall import recall_similar_findings

# query for the same kind of issue we just approved in Part A/B, same repo
results = recall_similar_findings(
    rule="LATEST_IMAGE_TAG",
    message="Using latest tag for container image",
    file_path="deployment.yaml",
    repo_name=REPO_NAME,
)

print(f"recall_similar_findings() returned {len(results)} past incident(s) for repo '{REPO_NAME}':")
for r in results:
    print(f"  - {r.get('rule')} (similarity={r.get('similarity')}) -> {r.get('approved_fix')}")

if results:
    print("\nPASS: the agent can recall what it learned earlier from THIS repo.")
else:
    print("\nNOTE: no results — either the embedding/rule text didn't match closely enough,")
    print("or MIN_SCORE (0.80) filtered it out. Try adjusting the query text above and rerun")
    print("just this Part C section if Parts A/B succeeded but this shows 0.")

print("\n" + "=" * 70)
print("ALL PARTS COMPLETE. Review the Qdrant checkpoints above before deciding next steps.")
print("=" * 70)