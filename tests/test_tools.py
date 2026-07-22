"""
Tests for Phase 2 tools.
Each tool is tested standalone with direct inputs.
"""

import os
import pytest
from unittest.mock import patch
from driftguard.tools import (
    get_full_manifest,
    get_related_resources,
    check_policy_rules,
    get_workload_history,
)

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), "..", "samples", "bad-manifests")
DEPLOYMENT_PATH = os.path.join(SAMPLES_DIR, "deployment.yaml")
DOCKERFILE_PATH = os.path.join(SAMPLES_DIR, "Dockerfile")


# --- get_full_manifest ---

def test_get_full_manifest_found():
    result = get_full_manifest(DEPLOYMENT_PATH)
    assert result.found is True
    assert "bad-app" in result.content
    assert result.error is None


def test_get_full_manifest_not_found():
    result = get_full_manifest("nonexistent/path/file.yaml")
    assert result.found is False
    assert result.error is not None


def test_get_full_manifest_dockerfile():
    result = get_full_manifest(DOCKERFILE_PATH)
    assert result.found is True
    assert "FROM" in result.content


# --- get_related_resources ---

def test_get_related_resources_finds_match():
    result = get_related_resources(name="bad-app", namespace="default", search_dir=SAMPLES_DIR)
    assert result.query_name == "bad-app"
    assert len(result.matches) >= 1


def test_get_related_resources_no_match():
    result = get_related_resources(name="nonexistent-service", namespace="prod", search_dir=SAMPLES_DIR)
    assert len(result.matches) == 0


# --- check_policy_rules ---

def test_check_policy_rules_bad_manifest():
    result = get_full_manifest(DEPLOYMENT_PATH)
    policy = check_policy_rules(DEPLOYMENT_PATH, result.content)
    assert policy.has_violations is True
    rules = [v.rule for v in policy.violations]
    assert "LATEST_TAG" in rules
    assert "NO_RESOURCE_LIMITS" in rules
    assert "PRIVILEGED_CONTAINER" in rules


def test_check_policy_rules_summary_not_empty():
    result = get_full_manifest(DEPLOYMENT_PATH)
    policy = check_policy_rules(DEPLOYMENT_PATH, result.content)
    assert len(policy.summary) > 0


# --- get_workload_history ---

def test_get_workload_history_no_history():
    with patch("driftguard.tools.history.recall_similar_findings", return_value=[]):
        result = get_workload_history("bad-app", repo_name="user/repo")
        assert result.workload_name == "bad-app"
        assert result.has_history is False
        assert result.incidents == []


def test_get_workload_history_returns_past_incidents():
    mock_past = [
        {
            "rule": "LATEST_TAG",
            "severity": "HIGH",
            "message": "Uses latest tag",
            "approved_fix": "Pin to nginx:1.25.0",
        }
    ]
    with patch("driftguard.tools.history.recall_similar_findings", return_value=mock_past):
        result = get_workload_history("bad-app", repo_name="user/repo")
        assert result.has_history is True
        assert result.incidents[0].severity == "HIGH"
        assert result.incidents[0].approved_fix == "Pin to nginx:1.25.0"
