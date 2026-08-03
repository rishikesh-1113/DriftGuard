"""
Tests for Phase 5 memory.
All Qdrant and embedding calls are mocked — no real API calls made.
"""

import pytest
from unittest.mock import patch, MagicMock
from driftguard.memory.store import build_embedding_text, store_approved_finding
from driftguard.memory.recall import recall_similar_findings


# --- build_embedding_text ---

def test_build_embedding_text_contains_all_fields():
    text = build_embedding_text(
        rule="LATEST_TAG",
        message="Uses latest tag",
        file_path="deployment.yaml",
        approved_fix="Pin to nginx:1.25.0",
    )
    assert "LATEST_TAG" in text
    assert "Uses latest tag" in text
    assert "deployment.yaml" in text
    assert "Pin to nginx:1.25.0" in text


# --- store_approved_finding ---

def test_store_approved_finding_calls_qdrant():
    mock_client = MagicMock()
    mock_client.get_collections.return_value.collections = []

    with patch("driftguard.memory.store.get_qdrant_client", return_value=mock_client), \
         patch("driftguard.memory.store.get_embedding", return_value=[0.1] * 768):

        point_id = store_approved_finding(
            rule="LATEST_TAG",
            severity="HIGH",
            message="Uses latest tag",
            reasoning="Unpredictable deployments",
            approved_fix="Pin to nginx:1.25.0",
            file_path="deployment.yaml",
            pr_number=1,
            repo_name="user/repo",
        )

        assert point_id is not None
        mock_client.upsert.assert_called_once()

# --- recall_similar_findings ---

def test_recall_returns_past_findings():
    mock_result = MagicMock()
    mock_result.score = 0.92
    mock_result.payload = {
        "rule": "LATEST_TAG",
        "severity": "HIGH",
        "message": "Uses latest tag",
        "approved_fix": "Pin to nginx:1.25.0",
        "file_path": "deployment.yaml",
        "pr_number": 1,
    }

    mock_response = MagicMock()
    mock_response.points = [mock_result]

    mock_client = MagicMock()
    mock_client.get_collections.return_value.collections = []
    mock_client.query_points.return_value = mock_response

with patch("driftguard.memory.recall.get_qdrant_client", return_value=mock_client), \
         patch("driftguard.memory.recall.ensure_collection_exists"), \
         patch("driftguard.memory.recall.get_embedding", return_value=[0.1] * 768):

        results = recall_similar_findings(
            rule="LATEST_TAG",
            message="Uses latest tag",
            file_path="deployment.yaml",
            repo_name="user/repo",
        )

        assert len(results) == 1
        assert results[0]["rule"] == "LATEST_TAG"
        assert results[0]["approved_fix"] == "Pin to nginx:1.25.0"
        assert results[0]["similarity"] == 0.92


def test_recall_returns_empty_on_failure():
    with patch("driftguard.memory.store.QdrantClient", side_effect=Exception("connection failed")):
        results = recall_similar_findings("LATEST_TAG", "Uses latest tag", "deployment.yaml", "user/repo")
        assert results == []