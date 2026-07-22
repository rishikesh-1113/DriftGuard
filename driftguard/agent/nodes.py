"""
LangGraph nodes for DriftGuard.
Each function is one node in the graph.
Nodes only read/write AgentState — no side effects outside of that.
"""

import json
import logging
import re
import os
from typing import Any
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import tool

from driftguard.agent.state import AgentState, ReviewFinding
from driftguard.tools import (
    get_full_manifest,
    get_related_resources,
    check_policy_rules,
    get_workload_history,
)

MAX_ITERATIONS = 5  # prevent infinite tool-calling loops

# Max lengths to prevent prompt injection via oversized inputs
_MAX_CONTENT_LEN = 20_000
_MAX_PATH_LEN = 500
_MAX_DIFF_LEN = 10_000


def _sanitize_for_prompt(text: str, max_len: int) -> str:
    """Strip control characters and truncate to prevent prompt injection."""
    if not text:
        return ""
    # Remove null bytes and other dangerous control chars (keep newlines/tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text[:max_len]

# ---------------------------------------------------------------------------
# LangChain tool definitions (these are what the LLM can call)
# ---------------------------------------------------------------------------

@tool
def tool_get_full_manifest(path: str) -> str:
    """Get the full content of a Kubernetes manifest or Dockerfile at the given path."""
    result = get_full_manifest(path)
    if not result.found:
        return f"Error: {result.error}"
    return result.content


@tool
def tool_check_policy_rules(path: str, content: str) -> str:
    """Run rule-based policy checks on a manifest or Dockerfile. Returns all violations found."""
    result = check_policy_rules(path, content)
    return result.summary


@tool
def tool_get_related_resources(name: str, namespace: str) -> str:
    """Find other Kubernetes manifests in the repo that reference the given resource name and namespace."""
    result = get_related_resources(name, namespace)
    if not result.matches:
        return f"No related resources found for '{name}' in namespace '{namespace}'."
    lines = [f"- [{m.kind}] {m.name} (namespace: {m.namespace}) at {m.path}" for m in result.matches]
    return "\n".join(lines)


def make_tool_get_workload_history(repo_name: str):
    """
    Builds the workload-history tool bound to the current repo.
    The LLM only ever supplies `name` — repo_name is injected here from
    pipeline state so results stay scoped to the repo being reviewed.
    """
    @tool
    def tool_get_workload_history(name: str) -> str:
        """Get past incidents and approved fixes for a workload. Returns empty if no history exists yet."""
        result = get_workload_history(name, repo_name)
        if not result.has_history:
            return f"No past incidents found for workload '{name}'."
        lines = [f"- [{i.severity}] {i.issue} | fix: {i.approved_fix}" for i in result.incidents]
        return "\n".join(lines)
    return tool_get_workload_history


def build_tools(repo_name: str):
    """Rebuilds the tool list per-invocation so history lookups are scoped to repo_name."""
    return [
        tool_get_full_manifest,
        tool_check_policy_rules,
        tool_get_related_resources,
        make_tool_get_workload_history(repo_name),
    ]

# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

def get_llm(repo_name: str = ""):
    from dotenv import load_dotenv
    load_dotenv()
    model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
    llm = ChatGoogleGenerativeAI(model=model_name, temperature=0)
    return llm.bind_tools(build_tools(repo_name))


SYSTEM_PROMPT = """You are DriftGuard, an expert Kubernetes and Docker configuration reviewer.

Your job is to analyze a manifest or Dockerfile and identify configuration issues that could cause:
- Security vulnerabilities (privileged containers, hardcoded secrets, running as root)
- Reliability problems (missing probes, no resource limits)
- Operational risks (latest tags, missing USER directive)

You have access to tools to gather more evidence before making a judgment.
Use them when you need more context — but don't call tools unnecessarily.

When you have enough information, respond with a JSON array of findings:
[
  {
    "rule": "RULE_NAME",
    "severity": "HIGH|MEDIUM|LOW",
    "message": "short description of the issue",
    "reasoning": "why this is a problem in production",
    "suggested_fix": "concrete fix with example",
    "confidence": 0.0-1.0
  }
]

If there are no issues, respond with an empty array: []
Only respond with the JSON array — no extra text.
"""

# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

def collect(state: AgentState) -> AgentState:
    """
    Collect node: builds the initial review context.
    Reads the file content if not already provided.
    """
    if not state.get("file_content") and state.get("file_path"):
        result = get_full_manifest(state["file_path"])
        state["file_content"] = result.content if result.found else ""

    state.setdefault("past_incidents", [])
    state.setdefault("findings", [])
    state.setdefault("iterations", 0)
    state.setdefault("messages", [])
    state.setdefault("pr_comment", None)
    state.setdefault("diff", None)
    return state


def recall(state: AgentState) -> AgentState:
    """
    Recall node: queries Qdrant for similar past approved findings.
    If similar findings exist, passes them to diagnose as context.
    Falls back to empty if memory unavailable.
    """
    from driftguard.memory.recall import recall_similar_findings

    # we don't know the rule yet at recall time, so search by file path + content snippet
    file_path = state.get("file_path", "")
    content_snippet = state.get("file_content", "")[:500]  # first 500 chars as context

    past = recall_similar_findings(
        rule="general",
        message=content_snippet,
        file_path=file_path,
        repo_name=state.get("repo_name", ""),
    )
    state["past_incidents"] = past
    return state


def diagnose(state: AgentState) -> AgentState:
    """
    Diagnose node: LLM reasons about the manifest.
    Either calls a tool for more evidence, or submits final findings.
    This is the core ReAct loop node.
    """
    llm = get_llm(state.get("repo_name", ""))

    # build context for the LLM — sanitize all user-controlled inputs
    safe_content = _sanitize_for_prompt(state.get("file_content", ""), _MAX_CONTENT_LEN)
    safe_path = _sanitize_for_prompt(state.get("file_path", ""), _MAX_PATH_LEN)
    safe_diff = _sanitize_for_prompt(state.get("diff", "") or "", _MAX_DIFF_LEN)

    past_context = ""
    if state["past_incidents"]:
        past_context = "\n\nPast incidents for reference:\n" + json.dumps(state["past_incidents"], indent=2)

    diff_context = ""
    if safe_diff:
        diff_context = f"\n\nDiff (what changed):\n{safe_diff}"

    user_message = HumanMessage(content=(
        f"Review this file: {safe_path}\n\n"
        f"Full content:\n{safe_content}"
        f"{diff_context}"
        f"{past_context}"
    ))

    # first call: build messages from scratch
    if not state["messages"]:
        state["messages"] = [SystemMessage(content=SYSTEM_PROMPT), user_message]

    state["iterations"] += 1
    response = llm.invoke(state["messages"])
    state["messages"].append(response)

    # if no tool calls — LLM gave final answer
    if not response.tool_calls:
        try:
            content = response.content
            # Gemini returns a list of parts — extract only text parts
            if isinstance(content, list):
                content = "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                    if not (isinstance(p, dict) and p.get("type") == "tool_use")
                )
            # extract JSON array — find first [ and last ]
            start = content.find("[")
            end = content.rfind("]") + 1
            if start != -1 and end > start:
                content = content[start:end]
            findings_raw = json.loads(content.strip())
            state["findings"] = findings_raw if isinstance(findings_raw, list) else []
        except (json.JSONDecodeError, TypeError) as e:
            logging.warning("[diagnose] failed to parse LLM findings: %s", e)
            state["findings"] = []

    return state


def run_tools(state: AgentState) -> AgentState:
    """
    Tools node: executes whatever tool the LLM called, appends result to messages.
    Then routes back to diagnose.
    """
    last_message = state["messages"][-1]

    tools = build_tools(state.get("repo_name", ""))
    tool_map = {t.name: t for t in tools}

    for tool_call in last_message.tool_calls:
        tool_name = tool_call["name"]
        tool_args = tool_call["args"]
        tool_id = tool_call["id"]

        if tool_name in tool_map:
            tool_result = tool_map[tool_name].invoke(tool_args)
        else:
            tool_result = f"Unknown tool: {tool_name}"

        state["messages"].append(ToolMessage(content=str(tool_result), tool_call_id=tool_id))

    return state


def propose(state: AgentState) -> AgentState:
    """
    Propose node: formats findings into a PR comment (markdown).
    """
    if not state["findings"]:
        state["pr_comment"] = "**DriftGuard Review:** No issues found. Looks good!"
        return state

    severity_prefix = {"HIGH": "[HIGH]", "MEDIUM": "[MEDIUM]", "LOW": "[LOW]"}

    lines = ["**DriftGuard Review**\n"]
    lines.append(f"Reviewed: `{state['file_path']}`\n")

    for f in state["findings"]:
        prefix = severity_prefix.get(f.get("severity", "LOW"), "[LOW]")
        lines.append(f"---\n{prefix} **{f.get('rule')}**")
        lines.append(f"- **Issue:** {f.get('message')}")
        lines.append(f"- **Why it matters:** {f.get('reasoning')}")
        lines.append(f"- **Suggested fix:** {f.get('suggested_fix')}")
        lines.append(f"- **Confidence:** {f.get('confidence', 0):.0%}\n")

    lines.append("---")
    lines.append("*Human approval required before applying any fix.*")

    state["pr_comment"] = "\n".join(lines)
    return state


def record(state: AgentState) -> AgentState:
    """
    Record node: does NOT write to Qdrant. It only filters findings down to the
    high-confidence ones and parks them in state["pending_approval_findings"].

    Actually writing to memory now happens only in handle_approval() (webhook.py),
    when a human comments /approve on the PR — that's the real trigger, not
    LLM confidence alone.
    """
    state["pending_approval_findings"] = [
        finding for finding in state.get("findings", [])
        if finding.get("confidence", 0) >= 0.85
    ]
    return state