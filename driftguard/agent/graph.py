"""
DriftGuard LangGraph graph.
Wires all nodes together:
  collect -> recall -> diagnose <-> tools -> propose -> record
"""

from langgraph.graph import StateGraph, END

from driftguard.agent.state import AgentState
from driftguard.agent.nodes import collect, recall, diagnose, run_tools, propose, record, MAX_ITERATIONS


def should_continue(state: AgentState) -> str:
    """
    Routing function after diagnose node.
    - If LLM called a tool AND we haven't hit the iteration limit: go to tools node
    - Otherwise: go to propose
    """
    last_message = state["messages"][-1]
    has_tool_calls = bool(getattr(last_message, "tool_calls", None))

    if has_tool_calls and state["iterations"] < MAX_ITERATIONS:
        return "tools"
    return "propose"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("collect", collect)
    graph.add_node("recall", recall)
    graph.add_node("diagnose", diagnose)
    graph.add_node("tools", run_tools)
    graph.add_node("propose", propose)
    graph.add_node("record", record)

    graph.set_entry_point("collect")

    graph.add_edge("collect", "recall")
    graph.add_edge("recall", "diagnose")

    # ReAct loop: diagnose either calls tools or moves to propose
    graph.add_conditional_edges("diagnose", should_continue, {
        "tools": "tools",
        "propose": "propose",
    })

    # after tools run, go back to diagnose
    graph.add_edge("tools", "diagnose")

    graph.add_edge("propose", "record")
    graph.add_edge("record", END)

    return graph.compile()


# single compiled graph instance
agent = build_graph()
