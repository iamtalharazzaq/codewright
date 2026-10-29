"""The architecture-change playbook as a LangGraph `StateGraph` (CODEWRIGHT.md Section 5.18).

Designs for every target and changes the code for clean modules and a modular monolith (Phase 15, `design.py`):

    intake → G1 → baseline → as_is → G2 → to_be → G3 → [languages → G4, for service designs]
      ├─ audit:      audit_report → G8 → deliver
      └─ conversion: restructure → verify → approve_result → report → G8 → deliver

The microservices conversion (Phases 16-17) is still simulated (`simulate`), with its original flow:

    intake → G1 → baseline → as_is → G2 → to_be → G3 → languages → G4
      ├─ audit:      audit_report → G8 → deliver
      └─ conversion: foundation → service loop (build_service → G5, per service) → db_split → G6
                     → frontend → G7 → report → G8 → deliver

Edit or Reject at a gate sends the run back to the step the gate reviews; what the user typed is the step's feedback.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent.playbooks.architecture_change import microservices
from agent.playbooks.architecture_change.design import REAL as DESIGN_REAL
from agent.playbooks.architecture_change.design import SERVICE_TARGETS
from agent.playbooks.architecture_change.steps import STEPS, MicroservicesInputs, MicroservicesState, stub_step
from agent.playbooks.gates import GateDef, after_gate, gate_node, last_decision, result_gate
from agent.playbooks.registry import PlaybookSpec
from agent.playbooks.services import RunServices
from agent.playbooks.state import Node

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
# The real flow shows Markdown briefs on the cards (the card renders them when every summary value is text).
BRIEFS = {
    "gate1": "intake_brief",
    "gate2": "as_is_brief",
    "gate3": "to_be_brief",
    "gate4": "language_brief",
    "gate8": "report_brief",
}
# The microservices conversion's gates (5-7) show their own briefs too.
CONVERSION_BRIEFS = {"gate5": "service_brief", "gate6": "db_split_brief", "gate7": "frontend_brief"}
REAL_GATES: dict[str, GateDef] = {
    g: replace(GATES[g], summary_keys=(key,)) for g, key in {**BRIEFS, **CONVERSION_BRIEFS}.items()
}
REAL = {**DESIGN_REAL, **microservices.REAL}
RESULT_GATE = result_gate(reworks="restructure", summary_keys=("result_brief",))

AUDIT_FLOW = ["intake", "gate1", "baseline", "as_is", "gate2", "to_be", "gate3", "languages", "gate4",
              "audit_report", "gate8", "deliver"]  # fmt: skip
CONVERSION_FLOW = [*AUDIT_FLOW[:9], "foundation", "build_service", "gate5", "db_split", "gate6", "frontend", "gate7",
                   "report", "gate8", "deliver"]  # fmt: skip


def flow(inputs: dict[str, Any]) -> list[str]:
    if inputs.get("simulate") or (inputs.get("target") == "microservices" and inputs.get("mode") != "audit"):
        return AUDIT_FLOW if inputs.get("mode") == "audit" else CONVERSION_FLOW
    head = ["intake", "gate1", "baseline", "as_is", "gate2", "to_be", "gate3"]
    if inputs.get("target") in SERVICE_TARGETS:
        head += ["languages", "gate4"]
    if inputs.get("mode") == "audit":
        return [*head, "audit_report", "gate8", "deliver"]
    return [*head, "restructure", "verify", RESULT_GATE.id, "report", "gate8", "deliver"]


def _after_design(state: MicroservicesState) -> str:
    """Where the run goes once the design (and, for service designs, the languages) is approved."""
    inputs = state["inputs"]
    if inputs.get("mode") == "audit":
        return "audit_report"
    return "foundation" if inputs.get("simulate") or inputs.get("target") == "microservices" else "restructure"


def _step_node(step: str, services: RunServices) -> Node[MicroservicesState]:
    """The real step, or its stub when the run is simulated."""
    stub = stub_step(step, services)
    real = REAL.get(step)

    async def node(state: MicroservicesState) -> dict[str, Any]:
        if real is None or state["inputs"].get("simulate"):
            return await stub(state)
        return await real(services, state)

    return node


def _gate(gate_id: str) -> Node[MicroservicesState]:
    """A gate whose card shows the Markdown brief of the real flow, or the raw summary of the simulated one."""
    simulated: Node[MicroservicesState] = gate_node(GATES[gate_id])
    real: Node[MicroservicesState] = gate_node(REAL_GATES[gate_id])

    async def node(state: MicroservicesState) -> dict[str, Any]:
        return await (simulated if state["inputs"].get("simulate") else real)(state)

    return node


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
    loop.add_node("build_service", _step_node("build_service", services))
    loop.add_node("gate5", _gate("gate5"))
    loop.add_edge(START, "next_service")
    loop.add_conditional_edges("next_service", has_service, ["build_service", END])
    loop.add_edge("build_service", "gate5")
    loop.add_conditional_edges("gate5", after_gate5, ["build_service", "next_service", END])
    return loop.compile()


def build(services: RunServices) -> Graph:
    g: Graph = StateGraph(MicroservicesState)
    shared = (
        "intake",
        "baseline",
        "as_is",
        "to_be",
        "languages",
        "audit_report",
        "restructure",
        "verify",
        "report",
        "deliver",
    )
    for step in shared:
        g.add_node(step, _step_node(step, services))
    for step in ("foundation", "db_split", "frontend"):
        g.add_node(step, _step_node(step, services))
    for gate_id in (*BRIEFS, "gate6", "gate7"):
        g.add_node(gate_id, _gate(gate_id))
    g.add_node(RESULT_GATE.id, gate_node(RESULT_GATE))
    g.add_node("service_loop", _build_service_loop(services))

    g.add_edge(START, "intake")
    g.add_edge("intake", "gate1")
    g.add_conditional_edges("gate1", after_gate("gate1", "baseline", "intake"), ["baseline", "intake"])
    g.add_edge("baseline", "as_is")
    g.add_edge("as_is", "gate2")
    g.add_conditional_edges("gate2", after_gate("gate2", "to_be", "as_is"), ["to_be", "as_is"])
    g.add_edge("to_be", "gate3")

    def after_gate3(state: MicroservicesState) -> str:
        if last_decision(state, "gate3") != "approve":
            return "to_be"
        inputs = state["inputs"]
        if inputs.get("simulate") or inputs.get("target") in SERVICE_TARGETS:
            return "languages"
        return _after_design(state)

    g.add_conditional_edges("gate3", after_gate3, ["to_be", "languages", "audit_report", "restructure", "foundation"])
    g.add_edge("languages", "gate4")

    def after_gate4(state: MicroservicesState) -> str:
        return _after_design(state) if last_decision(state, "gate4") == "approve" else "languages"

    g.add_conditional_edges("gate4", after_gate4, ["languages", "audit_report", "foundation", "restructure"])

    # Design only: the report, then delivery.
    g.add_edge("audit_report", "gate8")

    # Clean modules and modular monolith: small tested moves, then the proof.
    g.add_edge("restructure", "verify")
    g.add_edge("verify", RESULT_GATE.id)
    g.add_conditional_edges(
        RESULT_GATE.id, after_gate(RESULT_GATE.id, "report", "restructure"), ["report", "restructure"]
    )

    # The microservices conversion (real, or simulated with `simulate`). A foundation that could not be written ends
    # the conversion at the report: there is nothing to build services on.
    def after_foundation(state: MicroservicesState) -> str:
        if state["inputs"].get("simulate") or (state.get("foundation") or {}).get("ok"):
            return "service_loop"
        return "report"

    g.add_conditional_edges("foundation", after_foundation, ["service_loop", "report"])
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
    gates=(*GATES.values(), RESULT_GATE),
    build=build,
    flow=flow,
    min_tier=lambda inputs: 3 if inputs.get("target") == "microservices" else 2,
    initial_plan=initial_plan,
    needs_project_for=lambda inputs: not inputs.get("simulate"),
)
