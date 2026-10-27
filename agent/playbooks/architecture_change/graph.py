"""The architecture-change playbook as a LangGraph `StateGraph` (CODEWRIGHT.md Section 5.18): the microservices target,
stub steps for now.

    intake → G1 → baseline → as_is → G2 → to_be → G3 → languages → G4
      ├─ audit:      audit_report → G8 → deliver
      └─ conversion: foundation → service loop (build_service → G5, per service) → db_split → G6
                     → frontend → G7 → report → G8 → deliver

Edit or Reject at a gate sends the run back to the step the gate reviews.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.playbooks.architecture_change.steps import STEPS, MicroservicesInputs, MicroservicesState, stub_step
from agent.playbooks.gates import GateDef, after_gate, gate_node, last_decision
from agent.playbooks.registry import PlaybookSpec
from agent.playbooks.services import RunServices

Graph = StateGraph[MicroservicesState, None, MicroservicesState, MicroservicesState]


def _gate8_reworks(state: MicroservicesState) -> str:
    return "audit_report" if state["inputs"].get("mode") == "audit" else "report"


GATES: dict[str, GateDef] = {
    g.id: g
    for g in [
        GateDef("gate1", "Confirm goals", "Is the detected stack right, and are these your goals?", "intake",
                number=1, summary_keys=("stack", "goals")),
        GateDef("gate2", "Confirm As-Is", "Does this match how your system works today?", "as_is",
                number=2, summary_keys=("as_is",)),
        GateDef("gate3", "Approve design", "Approve these services and boundaries?", "to_be",
                number=3, summary_keys=("to_be",)),
        GateDef("gate4", "Pick languages", "Approve the language for each service?", "languages",
                number=4, summary_keys=("language_plan",)),
        GateDef("gate5", "Approve service PR", "Approve this service's PR and cut-over?", "build_service",
                number=5, summary_keys=("service_results",), subject_key="current_service"),
        GateDef("gate6", "Approve database split", "Approve the migration and rollback scripts?", "db_split",
                number=6, summary_keys=("db_split_stage",)),
        GateDef("gate7", "Approve UI", "Approve the new frontend?", "frontend",
                number=7, summary_keys=("frontend_status",)),
        GateDef("gate8", "Choose delivery", "Where should the result be delivered?", "report",
                number=8, summary_keys=("report", "delivery"), rework_for=_gate8_reworks),
    ]
}  # fmt: skip

AUDIT_FLOW = ["intake", "gate1", "baseline", "as_is", "gate2", "to_be", "gate3", "languages", "gate4",
              "audit_report", "gate8", "deliver"]  # fmt: skip
CONVERSION_FLOW = [*AUDIT_FLOW[:9], "foundation", "build_service", "gate5", "db_split", "gate6", "frontend", "gate7",
                   "report", "gate8", "deliver"]  # fmt: skip


def flow(inputs: dict[str, Any]) -> list[str]:
    return AUDIT_FLOW if inputs.get("mode") == "audit" else CONVERSION_FLOW


def _build_service_loop(services: RunServices) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Step 7 sub-graph: one service at a time from `service_queue`, each ending at Gate 5."""

    async def next_service(state: MicroservicesState) -> dict[str, Any]:
        queue = list(state.get("service_queue", []))
        return {"current_service": queue[0] if queue else None, "service_queue": queue[1:]}

    def after_gate5(state: MicroservicesState) -> str:
        if last_decision(state, "gate5") != "approve":
            return "build_service"
        return "next_service" if state.get("service_queue") else END

    def has_service(state: MicroservicesState) -> str:
        return "build_service" if state.get("current_service") else END

    loop: Graph = StateGraph(MicroservicesState)
    loop.add_node("next_service", next_service)
    loop.add_node("build_service", stub_step("build_service", services))
    loop.add_node("gate5", gate_node(GATES["gate5"]))
    loop.add_edge(START, "next_service")
    loop.add_conditional_edges("next_service", has_service, ["build_service", END])
    loop.add_edge("build_service", "gate5")
    loop.add_conditional_edges("gate5", after_gate5, ["build_service", "next_service", END])
    return loop.compile()


def build(services: RunServices) -> Graph:
    g: Graph = StateGraph(MicroservicesState)
    for step in STEPS:
        if step != "build_service":
            g.add_node(step, stub_step(step, services))
    for gate_id, gate in GATES.items():
        if gate_id != "gate5":
            g.add_node(gate_id, gate_node(gate))
    g.add_node("service_loop", _build_service_loop(services))

    g.add_edge(START, "intake")
    g.add_edge("intake", "gate1")
    g.add_conditional_edges("gate1", after_gate("gate1", "baseline", "intake"), ["baseline", "intake"])
    g.add_edge("baseline", "as_is")
    g.add_edge("as_is", "gate2")
    g.add_conditional_edges("gate2", after_gate("gate2", "to_be", "as_is"), ["to_be", "as_is"])
    g.add_edge("to_be", "gate3")
    g.add_conditional_edges("gate3", after_gate("gate3", "languages", "to_be"), ["languages", "to_be"])
    g.add_edge("languages", "gate4")

    def after_gate4(state: MicroservicesState) -> str:
        if last_decision(state, "gate4") != "approve":
            return "languages"
        return "audit_report" if state["inputs"].get("mode") == "audit" else "foundation"

    g.add_conditional_edges("gate4", after_gate4, ["languages", "audit_report", "foundation"])

    # Audit only: the audit report, then delivery.
    g.add_edge("audit_report", "gate8")

    # Full conversion.
    g.add_edge("foundation", "service_loop")
    g.add_edge("service_loop", "db_split")
    g.add_edge("db_split", "gate6")
    g.add_conditional_edges("gate6", after_gate("gate6", "frontend", "db_split"), ["frontend", "db_split"])
    g.add_edge("frontend", "gate7")
    g.add_conditional_edges("gate7", after_gate("gate7", "report", "frontend"), ["report", "frontend"])
    g.add_edge("report", "gate8")

    def after_gate8(state: MicroservicesState) -> str:
        if last_decision(state, "gate8") == "approve":
            return "deliver"
        return _gate8_reworks(state)

    g.add_conditional_edges("gate8", after_gate8, ["deliver", "audit_report", "report"])
    g.add_edge("deliver", END)
    return g


def initial_plan(inputs: dict[str, Any]) -> list[tuple[str, str, str]]:
    return [(s, STEPS[s].title, STEPS[s].role) for s in flow(inputs) if s in STEPS]


PLAYBOOK_SPEC = PlaybookSpec(
    inputs=MicroservicesInputs,
    steps=tuple(STEPS.values()),
    gates=tuple(GATES.values()),
    build=build,
    flow=flow,
    min_tier=lambda inputs: 3 if inputs.get("target") == "microservices" else 2,
    initial_plan=initial_plan,
)
