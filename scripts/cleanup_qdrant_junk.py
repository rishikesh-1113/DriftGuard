"""
Cleans up the old junk points in Qdrant that were written before the
approval-gating fix — these all have pr_number == 0 and an empty repo_name,
since the old record() node stored things automatically without a real PR
context.

This script PREVIEWS what would be deleted first and asks for confirmation
before deleting anything. Nothing is deleted silently.

Usage:
  cd DriftGuard
  python scripts/cleanup_qdrant_junk.py
"""

import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from qdrant_client import QdrantClient

QDRANT_URL = os.getenv("QDRANT_URL")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
COLLECTION_NAME = "driftguard_reviews"

if not QDRANT_URL or not QDRANT_API_KEY:
    print("QDRANT_URL and QDRANT_API_KEY must be set in .env")
    sys.exit(1)

client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)

# --- fetch ALL points and filter client-side ---
# (server-side filtering on pr_number would need a payload index that this
# collection doesn't have — simpler to just filter in Python instead)
all_points = []
next_offset = None
while True:
    batch, next_offset = client.scroll(
        collection_name=COLLECTION_NAME,
        limit=100,
        offset=next_offset,
        with_payload=True,
    )
    all_points.extend(batch)
    if next_offset is None:
        break

points = [p for p in all_points if p.payload.get("pr_number") == 0]

if not points:
    print("No junk points found (pr_number == 0). Nothing to clean up.")
    sys.exit(0)

print(f"Found {len(points)} point(s) with pr_number == 0 (pre-fix junk data):\n")
for p in points:
    rule = p.payload.get("rule", "?")
    repo = p.payload.get("repo_name", "")
    print(f"  - {p.id}  rule={rule}  repo_name={repo!r}")

confirm = input(f"\nDelete these {len(points)} point(s) from '{COLLECTION_NAME}'? Type 'yes' to confirm: ")

if confirm.strip().lower() != "yes":
    print("Aborted — nothing was deleted.")
    sys.exit(0)

client.delete(
    collection_name=COLLECTION_NAME,
    points_selector=[p.id for p in points],
)

print(f"Deleted {len(points)} junk point(s). Cleanup complete.")