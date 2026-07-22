"""
Diagnostic: recall_similar_findings() has a bare `except Exception: return []`
that could be hiding a real error rather than genuinely finding "no match".
This calls the same underlying Qdrant search directly, WITHOUT the try/except,
so we can see the real error if there is one.
"""

import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from qdrant_client.models import Filter, FieldCondition, MatchValue
from driftguard.memory.store import (
    get_qdrant_client, get_embedding, build_embedding_text,
    ensure_collection_exists, COLLECTION_NAME,
)

REPO_NAME = "local/full-e2e-test"

client = get_qdrant_client()
ensure_collection_exists(client)

query_text = build_embedding_text("LATEST_IMAGE_TAG", "Using latest tag", "deployment.yaml", "")
query_vector = get_embedding(query_text)

print("Attempting filtered search (this is what recall_similar_findings does internally)...")
try:
    response = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        query_filter=Filter(must=[FieldCondition(key="repo_name", match=MatchValue(value=REPO_NAME))]),
        limit=3,
        score_threshold=0.80,
    )
    results = response.points
    print(f"SUCCESS — got {len(results)} result(s), no error.")
    for r in results:
        print(f"  score={r.score:.3f}  rule={r.payload.get('rule')}  repo_name={r.payload.get('repo_name')!r}")
except Exception as e:
    print(f"\n*** FAILED with a real exception (this is what's being silently swallowed): ***")
    print(f"{type(e).__name__}: {e}")

print("\n--- for comparison, the same search WITHOUT the repo_name filter ---")
try:
    response2 = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=3,
        score_threshold=0.80,
    )
    results2 = response2.points
    print(f"SUCCESS (unfiltered) — got {len(results2)} result(s).")
    for r in results2:
        print(f"  score={r.score:.3f}  rule={r.payload.get('rule')}  repo_name={r.payload.get('repo_name')!r}")
except Exception as e:
    print(f"FAILED even without filter: {type(e).__name__}: {e}")