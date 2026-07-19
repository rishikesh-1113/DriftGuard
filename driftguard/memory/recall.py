"""
Memory recall for DriftGuard.
Before diagnosis: queries Qdrant for similar past approved findings.
Passes them to the agent as context — "we've seen this before, team approved X fix."
"""

import os
from typing import List
from dotenv import load_dotenv
from qdrant_client.models import Filter, FieldCondition, MatchValue
from driftguard.memory.store import (
    get_qdrant_client,
    get_embedding,
    build_embedding_text,
    ensure_collection_exists,
    COLLECTION_NAME,
)

load_dotenv()

TOP_K = 3           # return top 3 most similar past findings
MIN_SCORE = 0.80    # only return if similarity is high enough to be useful


def recall_similar_findings(rule: str, message: str, file_path: str, repo_name: str) -> List[dict]:
    """
    Query Qdrant for past approved findings similar to the current issue.
    Returns a list of past incidents with their approved fixes.
    Only returns results above MIN_SCORE threshold to avoid noise.
    """
    try:
        client = get_qdrant_client()
        ensure_collection_exists(client)

        # Sanitize inputs before building query to prevent injection
        safe_rule = str(rule)[:100].strip()
        safe_message = str(message)[:500].strip()
        safe_file_path = str(file_path)[:200].strip()
        safe_repo_name = str(repo_name)[:200].strip() 
        query_text = build_embedding_text(safe_rule, safe_message, safe_file_path, "")
        query_vector = get_embedding(query_text)

        response = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=Filter(
                must=[FieldCondition(key="repo_name", match=MatchValue(value=safe_repo_name))]
            ),
            limit=TOP_K,
            score_threshold=MIN_SCORE,
        )
        results = response.points

        return [
            {
                "rule": r.payload.get("rule"),
                "severity": r.payload.get("severity"),
                "message": r.payload.get("message"),
                "approved_fix": r.payload.get("approved_fix"),
                "file_path": r.payload.get("file_path"),
                "pr_number": r.payload.get("pr_number"),
                "similarity": round(r.score, 2),
            }
            for r in results
        ]

    except Exception:
        # memory is non-critical — if it fails, agent still works without it
        return []