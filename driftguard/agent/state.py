"""
State definition for the DriftGuard LangGraph agent.
This is the single object that flows through every node in the graph.
Every node reads from it and writes back to it.
"""

from typing import List, Optional
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage


class ReviewFinding(TypedDict):
    """Structured output from the diagnose node."""
    rule: str
    severity: str        # HIGH, MEDIUM, LOW
    message: str
    reasoning: str
    suggested_fix: str
    confidence: float    # 0.0 to 1.0


class AgentState(TypedDict):
    # --- collect node fills these ---
    file_path: str
    file_content: str
    diff: Optional[str]
    repo_name: str  

    # --- recall node fills these ---
    past_incidents: List[dict]   # empty stub until Phase 5

    # --- diagnose node fills these ---
    messages: List[BaseMessage]  # LangGraph message history for tool-calling loop
    findings: List[ReviewFinding]
    iterations: int              # safety counter to prevent infinite tool loops

    # --- propose node fills these ---
    pr_comment: Optional[str]

    # --- record node fills this ---
    # High-confidence findings waiting for a human /approve before they're
    # written to Qdrant memory. NOT stored yet just because they're here.
    pending_approval_findings: List[ReviewFinding]