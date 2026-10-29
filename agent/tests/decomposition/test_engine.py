"""The decomposition engine, the layers, the recommendation and the Language Advisor on small module graphs."""

from __future__ import annotations

from typing import Any

import pytest

from agent.decomposition import engine, languages
from agent.decomposition.layers import layer_design, layer_of
from agent.decomposition.recommend import goals_in, recommend


def node(module: str, files: int = 6, symbols: int = 40, ext: str = "go", **extra: Any) -> dict[str, Any]:
    language = {"go": "Go", "py": "Python", "tsx": "TypeScript", "cpp": "C++"}[ext]
    return {
        "id": module,
        "label": module.rsplit("/", 1)[-1],
        "files": [f"{module}/f{i}.{ext}" for i in range(files)],
        "file_count": files,
        "symbols": symbols,
        "languages": {language: files},
        **extra,
    }


def edge(a: str, b: str, weight: int, **extra: Any) -> dict[str, Any]:
    return {"source": a, "target": b, "weight": weight, "relations": {}, "sources": [], **extra}


def goshop_like() -> dict[str, Any]:
    """A shop: five domains over a shared database package, and a React frontend."""
    nodes = [node(f"internal/{m}") for m in ("user", "product", "order", "payment", "notification")]
    nodes += [node("internal/db", files=3), node("web", files=12, ext="tsx")]
    edges = [
        edge("internal/order", "internal/user", 6), edge("internal/order", "internal/product", 9),
        edge("internal/order", "internal/payment", 7), edge("internal/order", "internal/notification", 4),
        edge("internal/payment", "internal/notification", 3), edge("internal/user", "internal/notification", 2),
        edge("web", "internal/order", 8), edge("web", "internal/product", 6), edge("web", "internal/user", 4),
        edge("internal/order", "internal/db", 5), edge("internal/product", "internal/db", 5),
        edge("internal/user", "internal/db", 4), edge("internal/payment", "internal/db", 3),
    ]  # fmt: skip
    return {"nodes": nodes, "edges": edges}


def test_louvain_finds_the_two_obvious_communities_and_is_deterministic() -> None:
    pairs = {
        ("a", "b"): 5.0,
        ("a", "c"): 5.0,
        ("b", "c"): 5.0,
        ("d", "e"): 5.0,
        ("d", "f"): 5.0,
        ("e", "f"): 5.0,
        ("c", "d"): 0.5,
    }
    first = engine.louvain(list("abcdef"), pairs)
    assert first == [["a", "b", "c"], ["d", "e", "f"]]
    assert engine.louvain(list("abcdef"), pairs) == first
    assert engine.louvain(["x", "y"], {}) == [["x"], ["y"]]  # no edges: nothing to group


def test_weights_combine_static_runtime_tables_and_cochange() -> None:
    plain = {"nodes": [node("a"), node("b")], "edges": [edge("a", "b", 3)]}
    richer = {
        "nodes": plain["nodes"],
        "edges": [
            edge(
                "a", "b", 3, sources=[{"source": "git_cochange", "commits": 8}, {"source": "table_writes", "count": 2}]
            )
        ],
    }
    assert engine.pair_weights(richer)[("a", "b")] > engine.pair_weights(plain)[("a", "b")] > 0
    disputed = {"nodes": plain["nodes"], "edges": [edge("a", "b", 3, disputed=True)]}
    assert engine.pair_weights(disputed) == {}  # a dependency the user says doesn't exist does not count


def test_a_shop_gets_one_frontend_and_backend_groups_without_cycles_or_nanos() -> None:
    best, others = engine.alternatives(goshop_like())
    kinds = {g["name"]: g["kind"] for g in best["groups"]}
    assert kinds["frontend"] == "frontend" and sum(k == "backend" for k in kinds.values()) >= 3
    assert best["violations"] == []
    assert {m for g in best["groups"] for m in g["modules"]} == {n["id"] for n in goshop_like()["nodes"]}  # none lost
    assert others and all("why_not" in o for o in others)
    text = "\n".join(engine.explain(best, others))
    assert "one frontend" in text and "Alternative:" in text


def test_modules_that_call_each_other_are_merged_with_the_reason() -> None:
    graph = {
        "nodes": [node("svc/a"), node("svc/b"), node("svc/c"), node("svc/d")],
        "edges": [
            edge("svc/a", "svc/b", 6),
            edge("svc/b", "svc/a", 6),
            edge("svc/c", "svc/d", 1),
            edge("svc/a", "svc/c", 1),
        ],
    }
    design = engine.decompose(graph, resolution=3.0)
    group_of = {m: g["name"] for g in design["groups"] for m in g["modules"]}
    assert group_of["svc/a"] == group_of["svc/b"]
    assert any("call each other" in line or "chatty" in line for line in design["rules_applied"])


def test_two_groups_that_write_the_same_table_are_merged() -> None:
    graph = {
        "nodes": [
            node("x/orders", tables_written=["orders"]),
            node("x/billing", tables_written=["orders", "invoices"]),
            node("x/mail"),
        ],
        "edges": [edge("x/orders", "x/mail", 4), edge("x/billing", "x/mail", 4)],
    }
    design = engine.decompose(graph, resolution=3.0)
    group_of = {m: g["name"] for g in design["groups"] for m in g["modules"]}
    assert group_of["x/orders"] == group_of["x/billing"]
    assert any("one owner per table" in line for line in design["rules_applied"])


def test_a_tiny_module_is_not_a_service_of_its_own() -> None:
    graph = {"nodes": [node("p/a", files=8), node("p/b", files=8), node("p/tiny", files=1, symbols=3)],
             "edges": [edge("p/a", "p/b", 3), edge("p/a", "p/tiny", 5)]}  # fmt: skip
    design = engine.decompose(graph, resolution=3.0)
    assert not any(g["modules"] == ["p/tiny"] for g in design["groups"])


def test_editing_a_design_revalidates_and_reports_what_the_edit_breaks() -> None:
    graph = goshop_like()
    best, _ = engine.alternatives(graph)
    backend = [g for g in best["groups"] if g["kind"] == "backend"]
    assert len(backend) >= 2
    moved = backend[1]["modules"][0]
    edited = engine.edit_design(graph, best, {"move": {"module": moved, "to": backend[0]["name"]}})
    assert edited["edited"] and any("You moved" in line for line in edited["rules_applied"])
    assert moved in next(g for g in edited["groups"] if g["name"] == backend[0]["name"])["modules"]
    # Splitting a module out of a merged group re-runs the rules as violations, never as silent merges.
    merged = engine.edit_design(graph, best, {"merge": [backend[0]["name"], backend[1]["name"]]})
    assert len([g for g in merged["groups"] if g["kind"] == "backend"]) == len(backend) - 1
    renamed = engine.edit_design(graph, best, {"rename": {"from": backend[0]["name"], "to": "billing"}})
    assert "billing" in {g["name"] for g in renamed["groups"]}
    assert any(
        "billing" in g["calls"] + g["called_by"] for g in renamed["groups"] if g["name"] != "billing"
    )  # links follow


@pytest.mark.parametrize(
    "edit",
    [
        {"move": {"module": "nope", "to": "x"}},
        {"merge": ["nope", "nada"]},
        {"explode": 1},
        {"split": {"group": "nope", "modules": []}},
    ],
)
def test_a_bad_edit_is_refused_with_a_reason(edit: dict[str, Any]) -> None:
    graph = goshop_like()
    best, _ = engine.alternatives(graph)
    with pytest.raises(ValueError, match=r"."):
        engine.edit_design(graph, best, edit)


def test_a_split_that_would_empty_a_group_is_refused() -> None:
    graph = goshop_like()
    best, _ = engine.alternatives(graph)
    group = next(g for g in best["groups"] if g["kind"] == "backend")
    with pytest.raises(ValueError, match="some, but not all"):
        engine.edit_design(graph, best, {"split": {"group": group["name"], "modules": group["modules"]}})


# ── layers ───────────────────────────────────────────────────────────────────
def test_layers_are_placed_by_name_and_outward_dependencies_are_found() -> None:
    assert layer_of("internal/handlers") == ("interface", True)
    assert layer_of("pkg/order_service") == ("application", True)
    assert layer_of("internal/billing") == ("domain", False)  # unplaced: the user is asked
    graph = {
        "nodes": [node("api"), node("services"), node("repository"), node("models")],
        "edges": [edge("api", "services", 3), edge("services", "repository", 2), edge("repository", "models", 2),
                  edge("models", "api", 1), edge("services", "api", 4)],
    }  # fmt: skip
    design = layer_design(graph)
    assert [(v["from"], v["to"]) for v in design["violations"]] == [("services", "api"), ("models", "api")]
    assert design["cycles"] == ["api ⇄ services"]
    assert design["unplaced"] == []
    assert layer_design(graph, {"repository": "domain"})["assignment"]["repository"] == "domain"


# ── recommendation ───────────────────────────────────────────────────────────
def test_a_small_project_is_recommended_clean_modules_and_microservices_are_not_justified() -> None:
    graph = {
        "nodes": [node("app", files=4, ext="py"), node("lib", files=3, ext="py")],
        "edges": [edge("app", "lib", 2)],
    }
    rec = recommend(graph, "make this cleaner")
    assert rec["target"] == "modules"
    assert any("Microservices are not recommended" in line for line in rec["why"])
    assert [c["target"] for c in rec["considered"]][-1] in {"microservices", "serverless", "merge", "event_driven"}


def test_microservices_need_both_a_reason_and_a_graph_that_splits() -> None:
    clusters = [[f"d{c}/m{i}" for i in range(3)] for c in range(4)]
    nodes = [node(m) for cluster in clusters for m in cluster]
    edges = [edge(a, b, 8) for cluster in clusters for a in cluster for b in cluster if a < b]
    edges += [edge("d0/m0", "d1/m0", 1), edge("d1/m1", "d2/m1", 1), edge("d2/m2", "d3/m2", 1)]
    graph = {"nodes": nodes, "edges": edges}

    def fit(rec: dict[str, Any]) -> int:
        return int(next(c["fit"] for c in rec["considered"] if c["target"] == "microservices"))

    without_goal = recommend(graph, "")
    with_goal = recommend(graph, "we need to scale and let teams deploy independently")
    assert fit(with_goal) >= 7 and with_goal["target"] == "microservices"
    assert fit(without_goal) < 7 and without_goal["target"] != "microservices"  # a clean split alone is not a reason
    assert fit(recommend(goshop_like(), "scale it")) < 7  # six modules: the cost outweighs the benefit


def test_goal_words_and_background_modules_steer_the_recommendation() -> None:
    assert goals_in("it is slow under load and the teams step on each other") == {"scale", "autonomy"}
    graph = {"nodes": [node("a"), node("b"), node("jobs/cron"), node("mail/notification")],
             "edges": [edge("a", "mail/notification", 2), edge("b", "mail/notification", 2), edge("a", "b", 1)]}  # fmt: skip  # noqa: E501
    rec = recommend(graph, "run the jobs as functions and decouple notifications with events")
    by = {c["target"]: c["fit"] for c in rec["considered"]}
    assert by["serverless"] >= 4 and by["event_driven"] >= 5


# ── language advisor ─────────────────────────────────────────────────────────
def test_the_original_language_is_kept_unless_another_clearly_wins() -> None:
    nodes = {
        "svc/orders": node("svc/orders", ext="py"),
        "svc/pricing": node("svc/pricing", files=4, ext="py", languages={"Python": 4}),
    }
    keep = languages.advise(languages.profile(["svc/orders"], nodes))
    assert (keep["language"], keep["mode"]) == ("Python", "extract") and "stays" in " ".join(keep["why"])
    heavy = languages.advise(languages.profile(["svc/pricing"], nodes))  # compute-heavy: C++ 5 vs Python 2
    assert (heavy["language"], heavy["mode"]) == ("C++", "translate") and "gap of 3" in " ".join(heavy["why"])


def test_a_big_codebase_is_not_rewritten_for_a_small_gain() -> None:
    nodes = {"svc/pricing": node("svc/pricing", files=60, ext="py")}
    assert languages.advise(languages.profile(["svc/pricing"], nodes))["mode"] == "extract"


def test_an_unsupported_original_language_gets_the_best_supported_one() -> None:
    nodes = {"svc/legacy": {**node("svc/legacy", ext="py"), "languages": {"Java": 9}}}
    advice = languages.advise(languages.profile(["svc/legacy"], nodes, allowed=["Go", "Python"]))
    assert (
        advice["mode"] == "translate"
        and advice["language"] in {"Go", "Python"}
        and "not one of the five" in " ".join(advice["why"])
    )
