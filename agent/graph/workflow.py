"""The MonoShift workflow as a LangGraph `StateGraph` (README Section 2.1 and 7.2).

    intake → G1 → baseline → as_is → G2 → to_be → G3 → languages → G4
      ├─ audit:      audit_report → G8 → deliver
      └─ conversion: foundation → service loop (build_service → G5, per service) → db_split → G6
                     → frontend → G7 → report → G8 → deliver

Edit or Reject at a gate sends the run back to the step the gate reviews (README: "sends the step back for rework").
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.graph.gates import gate_node, last_decision
from agent.graph.services import RunServices
from agent.graph.state import MonoShiftState
from agent.graph.steps import stub_step

Graph = StateGraph[MonoShiftState, None, MonoShiftState, MonoShiftState]


def _after_gate(gate_id: str, approved: str, rework: str):  # type: ignore[no-untyped-def]
    def route(state: MonoShiftState) -> str:
        return approved if last_decision(state, gate_id) == "approve" else rework

    return route


def _build_service_loop(services: RunServices) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Step 7 sub-graph: one service at a time from `service_queue`, each ending at Gate 5."""

    async def next_service(state: MonoShiftState) -> dict[str, Any]:
        queue = list(state.get("service_queue", []))
        return {"current_service": queue[0] if queue else None, "service_queue": queue[1:]}

    def after_gate5(state: MonoShiftState) -> str:
        if last_decision(state, "gate5") != "approve":
            return "build_service"
        return "next_service" if state.get("service_queue") else END

    def has_service(state: MonoShiftState) -> str:
        return "build_service" if state.get("current_service") else END

    loop: Graph = StateGraph(MonoShiftState)
    loop.add_node("next_service", next_service)
    loop.add_node("build_service", stub_step("build_service", services))
    loop.add_node("gate5", gate_node("gate5"))
    loop.add_edge(START, "next_service")
    loop.add_conditional_edges("next_service", has_service, ["build_service", END])
    loop.add_edge("build_service", "gate5")
    loop.add_conditional_edges("gate5", after_gate5, ["build_service", "next_service", END])
    return loop.compile()


def build_workflow(
    services: RunServices, checkpointer: BaseCheckpointSaver[Any] | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    g: Graph = StateGraph(MonoShiftState)
    for step in (
        "intake",
        "baseline",
        "as_is",
        "to_be",
        "languages",
        "audit_report",
        "foundation",
        "db_split",
        "frontend",
        "report",
        "deliver",
    ):
        g.add_node(step, stub_step(step, services))
    for gate in ("gate1", "gate2", "gate3", "gate4", "gate6", "gate7", "gate8"):
        g.add_node(gate, gate_node(gate))
    g.add_node("service_loop", _build_service_loop(services))

    g.add_edge(START, "intake")
    g.add_edge("intake", "gate1")
    g.add_conditional_edges("gate1", _after_gate("gate1", "baseline", "intake"), ["baseline", "intake"])
    g.add_edge("baseline", "as_is")
    g.add_edge("as_is", "gate2")
    g.add_conditional_edges("gate2", _after_gate("gate2", "to_be", "as_is"), ["to_be", "as_is"])
    g.add_edge("to_be", "gate3")
    g.add_conditional_edges("gate3", _after_gate("gate3", "languages", "to_be"), ["languages", "to_be"])
    g.add_edge("languages", "gate4")

    def after_gate4(state: MonoShiftState) -> str:
        if last_decision(state, "gate4") != "approve":
            return "languages"
        return "audit_report" if state["mode"] == "audit" else "foundation"

    g.add_conditional_edges("gate4", after_gate4, ["languages", "audit_report", "foundation"])

    # Mode B (audit) ends with the audit report, then delivery.
    g.add_edge("audit_report", "gate8")

    # Mode A (conversion).
    g.add_edge("foundation", "service_loop")
    g.add_edge("service_loop", "db_split")
    g.add_edge("db_split", "gate6")
    g.add_conditional_edges("gate6", _after_gate("gate6", "frontend", "db_split"), ["frontend", "db_split"])
    g.add_edge("frontend", "gate7")
    g.add_conditional_edges("gate7", _after_gate("gate7", "report", "frontend"), ["report", "frontend"])
    g.add_edge("report", "gate8")

    def after_gate8(state: MonoShiftState) -> str:
        if last_decision(state, "gate8") == "approve":
            return "deliver"
        return "audit_report" if state["mode"] == "audit" else "report"

    g.add_conditional_edges("gate8", after_gate8, ["deliver", "audit_report", "report"])
    g.add_edge("deliver", END)
    return g.compile(checkpointer=checkpointer)
