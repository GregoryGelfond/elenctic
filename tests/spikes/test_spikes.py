"""§9 spikes: confirm — not discover — the clingo/clingcon behaviours the facade
relies on (spec §9). Findings + doc citations live in the dev-diaries notes; the
assertions here are a living regression guard. Marked ``spike`` for selection.

This module is excluded from ``mypy`` (it exercises the dynamic clingcon theory API
and the ``Union[SolveHandle, SolveResult]`` return of ``solve``); it stays ruff-clean.
"""

import pytest
from clingo import Control
from clingo.solving import Model, ModelType


def _names(model: Model) -> frozenset[str]:
    return frozenset(s.name for s in model.symbols(shown=True))


@pytest.mark.spike
def test_cautious_reports_intersection_as_final_model() -> None:
    # §9.1/§9.4: `-e cautious` reports ⋂ as a final CautiousConsequences model.
    # 1{a;b}1. c.  →  AS = {a,c},{b,c}; ⋂ = {c}.
    ctl = Control(["--models=0", "--enum-mode=cautious"])
    ctl.add("base", [], "1 {a; b} 1. c.")
    ctl.ground([("base", [])])
    seen: list[tuple[ModelType, frozenset[str]]] = []
    ctl.solve(on_model=lambda m: seen.append((m.type, _names(m))))
    assert seen[-1][0] is ModelType.CautiousConsequences
    assert seen[-1][1] == frozenset({"c"})


@pytest.mark.spike
def test_brave_reports_union_as_final_model() -> None:
    # §9.1/§9.4: `-e brave` reports ⋃ as a final BraveConsequences model.
    ctl = Control(["--models=0", "--enum-mode=brave"])
    ctl.add("base", [], "1 {a; b} 1. c.")
    ctl.ground([("base", [])])
    seen: list[tuple[ModelType, frozenset[str]]] = []
    ctl.solve(on_model=lambda m: seen.append((m.type, _names(m))))
    assert seen[-1][0] is ModelType.BraveConsequences
    assert seen[-1][1] == frozenset({"a", "b", "c"})


@pytest.mark.spike
def test_default_enumeration_reports_distinct_stable_models() -> None:
    # The all-base run sees StableModels; --project gives distinct shown projections.
    ctl = Control(["--models=0", "--project"])
    ctl.add("base", [], "1 {a; b} 1. c. #show a/0. #show b/0.")
    ctl.ground([("base", [])])
    seen: list[tuple[ModelType, frozenset[str]]] = []
    ctl.solve(on_model=lambda m: seen.append((m.type, _names(m))))
    assert {t for t, _ in seen} == {ModelType.StableModel}
    assert {names for _, names in seen} == {frozenset({"a"}), frozenset({"b"})}


@pytest.mark.spike
def test_optN_models0_enumerates_whole_optimal_class_with_ties() -> None:
    # §9.2/TR7: --opt-mode=optN --models 0 enumerates ALL optimal models.
    # 1{a;b}1 each cost 1 → two co-optimal models, optimum cost (1,).
    ctl = Control(["--opt-mode=optN", "--models=0"])
    ctl.add("base", [], "1 {a; b} 1. #minimize {1,a:a; 1,b:b}.")
    ctl.ground([("base", [])])
    rows: list[tuple[tuple[int, ...], frozenset[str]]] = []
    ctl.solve(on_model=lambda m: rows.append((tuple(m.cost), _names(m))))
    optimum = min(c for c, _ in rows)
    optimal = {names for c, names in rows if c == optimum}
    assert optimum == (1,)
    assert optimal == {frozenset({"a"}), frozenset({"b"})}


@pytest.mark.spike
def test_minimize_cost_is_natural() -> None:
    # §9.1 / spec §2.0: for #minimize, model.cost is the natural value (no sign flip).
    ctl = Control(["--opt-mode=opt"])
    ctl.add("base", [], "1 {a; b} 1. #minimize {3,a:a; 1,b:b}.")
    ctl.ground([("base", [])])
    rows: list[tuple[int, ...]] = []
    ctl.solve(on_model=lambda m: rows.append(tuple(m.cost)))
    assert min(rows) == (1,)  # choosing b (cost 1) is optimal


@pytest.mark.spike
def test_maximize_cost_is_negated_internally() -> None:
    # spec §2.0 caveat: clingo reports #maximize in minimize-internal (negated) form,
    # so the facade must normalise if any encoding uses #maximize.
    ctl = Control(["--opt-mode=opt"])
    ctl.add("base", [], "1 {a; b} 1. #maximize {3,a:a; 1,b:b}.")
    ctl.ground([("base", [])])
    rows: list[tuple[int, ...]] = []
    ctl.solve(on_model=lambda m: rows.append(tuple(m.cost)))
    assert min(rows) == (-3,)  # maximizing picks a (value 3); internal cost is -3


@pytest.mark.spike
def test_timeout_path_yields_incomplete() -> None:
    # §9.5: async solve + wait(budget) + cancel composes; a zero-poll is "not finished".
    ctl = Control(["--models=0"])
    ctl.add("base", [], "{ p(1..28) }.")  # 2^28 models: not finished at a zero-poll
    ctl.ground([("base", [])])
    with ctl.solve(on_model=lambda m: None, async_=True) as handle:
        completed = handle.wait(0.0)
        if not completed:
            handle.cancel()
    assert completed is False


@pytest.mark.spike
def test_clingcon_csp_assignment_recoverable_and_multiplicity_observed() -> None:
    # §9.3/TR4 GATE: is a CSP variable's assignment recoverable, and are distinct CSP
    # solutions surfaced as distinct models under --models 0? The answer selects the
    # @count/@assign denotation: full multiplicity, or the pinned existence fallback.
    pytest.importorskip("clingcon")
    import clingcon
    from clingo.ast import ProgramBuilder, parse_string

    thy = clingcon.ClingconTheory()
    ctl = Control(["--models=0"])
    thy.register(ctl)
    with ProgramBuilder(ctl) as bld:
        parse_string("&dom {1..3} = x.", lambda ast: thy.rewrite_ast(ast, bld.add))
    ctl.ground([("base", [])])
    thy.prepare(ctl)
    assignments: list[dict[str, int]] = []

    def on_model(model: Model) -> None:
        thy.on_model(model)
        assignments.append({str(sym): val for sym, val in thy.assignment(model.thread_id)})

    ctl.solve(on_model=on_model)
    # CONFIRMED 2026-06-18 (clingcon 5.2.1): distinct CSP solutions ARE distinct models
    # under --models 0 (no --project) → @count/@assign over theory output denote
    # MULTIPLICITY, not the existence fallback. --project collapses this (3 → 1), so the
    # clingcon facade must never project (spec §3/§6.3).
    assert all("x" in a for a in assignments), "CSP variable x not recoverable"
    assert {a["x"] for a in assignments} == {1, 2, 3}
    assert len(assignments) == 3
