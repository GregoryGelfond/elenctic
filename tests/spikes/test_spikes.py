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
@pytest.mark.parametrize(
    "mode_args",
    [
        pytest.param(["--enum-mode=cautious"], id="cautious"),
        pytest.param(["--enum-mode=brave"], id="brave"),
        pytest.param([], id="default"),
    ],
)
def test_modes_on_unsat_emit_no_model_and_report_unsatisfiable(mode_args: list[str]) -> None:
    # Keystone anchor (the `Inconsistent` arm of the result `Determination`). On an UNSAT
    # program clingo emits ZERO models under every mode — no empty CautiousConsequences /
    # BraveConsequences final model — and reports `unsatisfiable` as a single whole-result
    # discriminant. So the facade decides Consistent/Inconsistent ONCE from
    # `result.unsatisfiable`, never by inferring UNSAT from an empty consequence field
    # (which is exactly the per-field-sum state clingo cannot produce). `a. :- a.` is UNSAT:
    # `a` is forced true, then forbidden, so there is no stable model.
    ctl = Control(["--models=0", *mode_args])
    ctl.add("base", [], "a. :- a.")
    ctl.ground([("base", [])])
    seen: list[tuple[ModelType, frozenset[str]]] = []
    result = ctl.solve(on_model=lambda m: seen.append((m.type, _names(m))))
    assert seen == []  # no model of any type — the empty-consequence-model trap does not occur
    assert result.unsatisfiable is True
    assert result.satisfiable is False
    assert result.exhausted is True  # UNSAT ⟹ exhausted: the closed-world claim is honest


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


def _clingcon_rows(program: str, args: list[str]) -> list[tuple[tuple[int, ...], dict[str, int]]]:
    """Run a clingcon program, returning (cost, assignment) per model — shared by the spikes."""
    import clingcon
    from clingo.ast import ProgramBuilder, parse_string

    thy = clingcon.ClingconTheory()
    ctl = Control(args)
    thy.register(ctl)
    with ProgramBuilder(ctl) as bld:
        parse_string(program, lambda ast: thy.rewrite_ast(ast, bld.add))
    ctl.ground([("base", [])])
    thy.prepare(ctl)
    rows: list[tuple[tuple[int, ...], dict[str, int]]] = []

    def on_model(model: Model) -> None:
        thy.on_model(model)
        rows.append((tuple(model.cost), {str(s): v for s, v in thy.assignment(model.thread_id)}))

    ctl.solve(on_model=on_model)
    return rows


@pytest.mark.spike
def test_clingcon_compound_term_assignment_is_recoverable() -> None:
    # §9 strengthening (BLOCKER): the §9.3 spike probed only a 0-ary `&dom = x`; the send-money
    # case needs a COMPOUND term `digit(s)`. Confirm a compound CSP variable's assignment is
    # recovered, and that with `#show.` the answer lives entirely in the assignment (§6.3).
    pytest.importorskip("clingcon")
    rows = _clingcon_rows("&dom {0..9} = digit(s). &sum { digit(s) } = 9. #show.", ["--models=0"])
    assert len(rows) == 1
    _, assignment = rows[0]
    assert assignment == {"digit(s)": 9}


@pytest.mark.spike
def test_clingcon_supports_clingo_minimize_optimization() -> None:
    # §9 strengthening (BLOCKER): clingcon × optimization was unconfirmed. Confirm clingo's
    # #minimize over regular ASP atoms works UNDER clingcon (the facade reads model.cost the same
    # way for both backends). Theory-native &minimize stays out of v1 scope (RR6b), unrelated.
    pytest.importorskip("clingcon")
    program = "1 {a; b} 1. #minimize { 2,a : a; 1,b : b }. #show a/0."
    rows = _clingcon_rows(program, ["--opt-mode=opt"])
    assert min(cost for cost, _ in rows) == (1,)  # picks b (cost 1) over a (cost 2)


def _clingcon_shown_rows(
    program: str, args: list[str]
) -> list[tuple[frozenset[str], dict[str, int]]]:
    """Run a clingcon program, returning (shown atoms, CSP assignment) per model."""
    import clingcon
    from clingo.ast import ProgramBuilder, parse_string

    thy = clingcon.ClingconTheory()
    ctl = Control(args)
    thy.register(ctl)
    with ProgramBuilder(ctl) as bld:
        parse_string(program, lambda ast: thy.rewrite_ast(ast, bld.add))
    ctl.ground([("base", [])])
    thy.prepare(ctl)
    rows: list[tuple[frozenset[str], dict[str, int]]] = []

    def on_model(model: Model) -> None:
        thy.on_model(model)
        rows.append((_names(model), {str(s): v for s, v in thy.assignment(model.thread_id)}))

    ctl.solve(on_model=on_model)
    return rows


@pytest.mark.spike
def test_clingcon_project_collapses_multiplicity_onto_shown_preserving_shown_set() -> None:
    # clingcon --project deduplicates by #show atoms, collapsing CSP multiplicity onto the shown
    # census while preserving the shown set exactly. `&dom {1..3} = x` with a constant shown atom
    # `ok`: without --project, 3 distinct CSP solutions share 1 shown class; with --project, exactly
    # 1 model, the shown set unchanged. The surviving projected model carries an ARBITRARY
    # representative assignment — which is why a projected shown-only census must withhold the
    # assignment (reading it would return a misleading representative).
    pytest.importorskip("clingcon")
    program = "&dom {1..3} = x. ok. #show ok/0."
    no_project = _clingcon_shown_rows(program, ["--models=0"])
    projected = _clingcon_shown_rows(program, ["--models=0", "--project"])
    assert len(no_project) == 3  # the 3 distinct CSP solutions are real (no projection)
    assert {shown for shown, _ in no_project} == {frozenset({"ok"})}  # one shown class { {ok} }
    assert len(projected) == 1  # --project collapses them to the single shown class
    assert {shown for shown, _ in projected} == {frozenset({"ok"})}  # shown set preserved exactly


@pytest.mark.spike
def test_clingo_opt_mode_enum_bound_is_cost_leq_bound() -> None:
    # --opt-mode=enum,<bound> enumerates exactly the models with cost <= bound. Proving the optimum
    # c* with --opt-mode=opt, then enumerating at enum,c*, yields exactly the optimal class: at a
    # single optimization level no cross-level deduplication can occur. The collision program below
    # shares one shown projection { mark } between the optimal {a} (cost 0) and the sub-optimal {b}
    # (cost 1) — the case most likely to expose a cross-level dedup loss, if one existed.
    program = "1 { a; b } 1. mark :- a. mark :- b. #minimize { 0,a : a; 1,b : b }. #show mark/0."
    ctl = Control(["--models=0"])
    ctl.add("base", [], program)
    ctl.ground([("base", [])])
    ctl.configuration.solve.opt_mode = "opt"
    proved: list[tuple[int, ...]] = []
    ctl.solve(on_model=lambda m: proved.append(tuple(m.cost)))
    cstar = min(proved)
    assert cstar == (0,)
    ctl.configuration.solve.opt_mode = "enum," + ",".join(str(c) for c in cstar)
    at_optimum: list[tuple[tuple[int, ...], frozenset[str]]] = []
    ctl.solve(on_model=lambda m: at_optimum.append((tuple(m.cost), _names(m))))
    assert all(cost == cstar for cost, _ in at_optimum)  # exactly the optimal class
    assert {names for _, names in at_optimum} == {frozenset({"mark"})}  # the shown optimal class


@pytest.mark.spike
def test_clingo_silently_accepts_theory_atom_when_theory_is_defined() -> None:
    # R1 hole (the reason the default-loud theory-presence gate exists): with a #theory block in
    # scope, clingo grounds and SILENTLY IGNORES theory atoms — SAT, no warning — where clingcon
    # would prune. `&sum { 1 } >= 5` is the false fact 1 >= 5; clingcon makes it UNSAT, clingo SAT.
    messages: list[str] = []
    program = "#theory t { lt { - : 3, unary }; &sum/0 : lt, {>=}, lt, head }. &sum { 1 } >= 5."
    ctl = Control(["--models=0"], logger=lambda _code, message: messages.append(message))
    ctl.add("base", [], program)
    ctl.ground([("base", [])])
    result = ctl.solve(on_model=lambda m: None)
    assert result.satisfiable is True  # the >= 5 constraint silently did not prune
    assert messages == []  # and clingo did not even warn


@pytest.mark.spike
def test_clingo_rejects_a_bare_theory_atom_with_no_theory_definition() -> None:
    # The "loud in practice" baseline: a bare &-atom with NO #theory in scope errors at grounding
    # (the usual clingcon corpus, where clingcon injects the theory), so a forgotten declaration is
    # loud there. The dangerous case is a program carrying its OWN #theory (above).
    ctl = Control(["--models=0"], message_limit=10)
    ctl.add("base", [], "&sum { x } >= 5.")
    with pytest.raises(RuntimeError):
        ctl.ground([("base", [])])
