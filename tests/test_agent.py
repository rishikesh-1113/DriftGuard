"""
Tests for Phase 3 agent.
Tests graph structure and individual nodes without calling OpenAI API.
"""

import pytest
from driftguard.agent.state import AgentState
from driftguard.agent.nodes import collect, recall, propose, record
from driftguard.agent.graph import build_graph, should_continue
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage


# --- collect node ---

def test_collect_reads_file_content():
    state = collect({
        "file_path": "samples/bad-manifests/deployment.yaml",
        "file_content": "",
    })
    assert len(state["file_content"]) > 0
    assert "payments-api" in state["file_content"]


def test_collect_sets_defaults():
    state = collect({"file_path": "samples/bad-manifests/deployment.yaml", "file_content": ""})
    assert state["past_incidents"] == []
    assert state["findings"] == []
    assert state["iterations"] == 0
    assert state["messages"] == []


# --- recall node ---

def test_recall_returns_empty_stub():
    state = recall({"past_incidents": [], "file_content": "anything"})
    assert state["past_incidents"] == []


# --- propose node ---

def test_propose_with_findings():
    findings = [{
        "rule": "LATEST_TAG",
        "severity": "HIGH",
        "message": "Uses latest tag",
        "reasoning": "Unpredictable deployments",
        "suggested_fix": "Pin to nginx:1.25.0",
        "confidence": 0.95,
    }]
    state = propose({"findings": findings, "file_path": "deployment.yaml"})
    assert "LATEST_TAG" in state["pr_comment"]
    assert "[HIGH]" in state["pr_comment"]
    assert "Human approval required" in state["pr_comment"]


def test_propose_no_findings():
    state = propose({"findings": [], "file_path": "deployment.yaml"})
    assert "No issues found" in state["pr_comment"]


# --- record node (stub) ---

def test_record_is_passthrough():
    state = {"findings": [], "pr_comment": "test"}
    result = record(state)
    assert result == state


# --- graph structure ---

def test_graph_compiles():
    graph = build_graph()
    assert graph is not None


def test_should_continue_routes_to_tools():
    mock_msg = MagicMock()
    mock_msg.tool_calls = [{"name": "tool_check_policy_rules", "args": {}, "id": "1"}]
    state = {"messages": [mock_msg], "iterations": 1}
    assert should_continue(state) == "tools"


def test_should_continue_routes_to_propose_when_no_tool_calls():
    mock_msg = MagicMock()
    mock_msg.tool_calls = []
    state = {"messages": [mock_msg], "iterations": 1}
    assert should_continue(state) == "propose"


def test_should_continue_routes_to_propose_when_max_iterations():
    mock_msg = MagicMock()
    mock_msg.tool_calls = [{"name": "tool_check_policy_rules", "args": {}, "id": "1"}]
    state = {"messages": [mock_msg], "iterations": 5}  # MAX_ITERATIONS = 5
    assert should_continue(state) == "propose"
