import threading
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from elenctic.determination import (
    Consequences,
    Consistent,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Incumbent,
    Mode,
    Model,
    NoAssumptions,
    NotThese,
    Optimum,
    These,
    Truncation,
    optimal_view,
    world_view,
)
from elenctic.engine import Fault, Interrupt, Limits, Locus, Program, ground, solve
from elenctic.literals import Assumption, Literal

P, Q = Literal("p"), Literal("q")


def stable_models(text: str, **kwargs: object) -> set[frozenset[Literal]]:
    found = solve(Program(text), **kwargs)  # type: ignore[arg-type]
    assert isinstance(found, Consistent), found
    assert found.conclusion is Exhausted.EXHAUSTED
    return {m.atoms for m in found.evidence.all}


def test_every_stable_model_is_found_and_none_twice() -> None:
    assert stable_models("{p;q}.") == {
        frozenset(),
        frozenset({P}),
        frozenset({Q}),
        frozenset({P, Q}),
    }


def test_an_objective_does_not_narrow_the_stable_models() -> None:
    assert len(stable_models("{p}. #minimize { 1 : p }.")) == 2


def test_a_model_carries_what_it_shows_apart_from_what_it_holds() -> None:
    found = solve(Program("p. q. #show p/0."))
    assert isinstance(found, Consistent)
    assert (found.evidence.first.atoms, found.evidence.first.shown) == (
        frozenset({P, Q}),
        frozenset({P}),
    )


def test_a_program_with_no_stable_model_is_inconsistent_with_nothing_to_blame() -> None:
    assert solve(Program("p. :- p.")) == Inconsistent(NoAssumptions())


def test_a_scenario_that_holds_restricts_the_models() -> None:
    assert stable_models("{p;q}.", scenario=frozenset({Assumption(P)})) == {
        frozenset({P}),
        frozenset({P, Q}),
    }


def test_a_scenario_that_fails_restricts_the_models() -> None:
    assert stable_models("{p;q}.", scenario=frozenset({Assumption(P, holds=False)})) == {
        frozenset(),
        frozenset({Q}),
    }


def test_an_unsatisfiable_scenario_is_refuted_by_the_assumptions_that_clash() -> None:
    clash = frozenset({Assumption(P), Assumption(Q)})
    found = solve(Program("{p;q}. :- p, q."), clash)
    assert isinstance(found, Inconsistent)
    assert found.refutation == These(clash)


def test_assuming_an_atom_no_rule_derives_is_refuted_by_it_alone() -> None:
    absent = Assumption(Literal("absent"))
    found = solve(Program("{p}."), frozenset({Assumption(P), absent}))
    assert found == Inconsistent(These(frozenset({absent})))


def test_assuming_such_an_atom_false_is_no_restriction() -> None:
    assert stable_models("{p}.", scenario=frozenset({Assumption(Literal("absent"), holds=False)}))


def test_assuming_a_fact_false_is_refuted() -> None:
    fact_denied = Assumption(P, holds=False)
    found = solve(Program("p."), frozenset({fact_denied}))
    assert found == Inconsistent(These(frozenset({fact_denied})))


def test_a_strongly_negated_literal_can_be_assumed() -> None:
    models = stable_models("{-p}.", scenario=frozenset({Assumption(P.contrary)}))
    assert models == {frozenset({P.contrary})}


def test_the_model_cap_truncates_without_claiming_to_have_finished() -> None:
    found = solve(Program("{p(1..5)}."), limits=Limits(models=3))
    assert isinstance(found, Consistent)
    assert found.conclusion is Truncation.TARGET
    assert len(found.evidence.all) == 3


def test_a_cap_equal_to_the_number_of_models_is_still_exhausted() -> None:
    found = solve(Program("{p;q}."), limits=Limits(models=4))
    assert isinstance(found, Consistent)
    assert (found.conclusion, len(found.evidence.all)) == (Exhausted.EXHAUSTED, 4)


def test_a_search_cut_by_the_budget_keeps_the_models_it_found() -> None:
    found = solve(Program("{p(1..40)}."), limits=Limits(seconds=0.2))
    assert isinstance(found, Consistent)
    assert found.conclusion is Truncation.BUDGET


def test_a_budget_spent_before_any_model_is_inconclusive_not_inconsistent() -> None:
    assert solve(Program("{p;q}."), limits=Limits(seconds=0)) == Inconclusive(Truncation.BUDGET)


def test_an_interrupt_pulled_from_another_thread_ends_the_search() -> None:
    interrupt = Interrupt()
    threading.Timer(0.1, interrupt.pull).start()
    found = solve(Program("{p(1..40)}."), interrupt=interrupt)
    assert isinstance(found, Consistent)
    assert found.conclusion is Truncation.INTERRUPTED


def test_an_interrupt_already_pulled_stops_before_the_search() -> None:
    interrupt = Interrupt()
    interrupt.pull()
    assert solve(Program("p."), interrupt=interrupt) == Inconclusive(Truncation.INTERRUPTED)


def test_a_limit_is_not_negative() -> None:
    with pytest.raises(ValueError, match="negative"):
        Limits(seconds=-1)


def test_a_syntax_error_is_a_fault_of_the_program_placed_in_it() -> None:
    found = solve(Program("p(1.\nq.", source="a.lp"))
    assert isinstance(found, Fault)
    assert found.locus is Locus.PROGRAM
    assert str(found.diagnostics[0].span) == "a.lp:1:4-5"


def test_an_unsafe_rule_is_a_fault_of_the_program() -> None:
    found = solve(Program("p(X) :- q(Y).", source="a.lp"))
    assert isinstance(found, Fault)
    assert "unsafe" in found.diagnostics[0].message


def test_a_program_read_from_a_file_resolves_its_includes_beside_it(tmp_path: Path) -> None:
    (tmp_path / "inc.lp").write_text("p.\n")
    (tmp_path / "main.lp").write_text('#include "inc.lp".\n')
    found = solve(Program.read(tmp_path / "main.lp"))
    assert isinstance(found, Consistent)
    assert found.evidence.first.atoms == {P}


def test_the_cautious_consequences_are_what_every_model_shares() -> None:
    grounded = ground(Program("{q}. p."))
    assert not isinstance(grounded, Fault)
    assert grounded.consequences(Mode.CAUTIOUS) == Consistent(
        Consequences(Mode.CAUTIOUS, frozenset({P})), Exhausted.EXHAUSTED
    )
    assert grounded.consequences(Mode.BRAVE) == Consistent(
        Consequences(Mode.BRAVE, frozenset({P, Q})), Exhausted.EXHAUSTED
    )


def test_consequences_are_read_among_the_shown_atoms() -> None:
    grounded = ground(Program("{q}. p. #show p/0."))
    assert not isinstance(grounded, Fault)
    assert grounded.consequences(Mode.BRAVE) == Consistent(
        Consequences(Mode.BRAVE, frozenset({P})), Exhausted.EXHAUSTED
    )


def test_consequences_of_an_inconsistent_program_are_inconsistent() -> None:
    grounded = ground(Program("p. :- p."))
    assert not isinstance(grounded, Fault)
    assert grounded.consequences(Mode.CAUTIOUS) == Inconsistent(NoAssumptions())


def test_a_truncated_consequence_search_claims_nothing() -> None:
    grounded = ground(Program("{p(1..40)}."))
    assert not isinstance(grounded, Fault)
    assert grounded.consequences(Mode.BRAVE, limits=Limits(seconds=0)) == Inconclusive(
        Truncation.BUDGET
    )


def test_one_grounding_serves_many_scenarios() -> None:
    grounded = ground(Program("{p;q}."))
    assert not isinstance(grounded, Fault)
    with_p = grounded.solve(frozenset({Assumption(P)}))
    without_p = grounded.solve(frozenset({Assumption(P, holds=False)}))
    assert isinstance(with_p, Consistent)
    assert isinstance(without_p, Consistent)
    assert all(P in m.atoms for m in with_p.evidence.all)
    assert all(P not in m.atoms for m in without_p.evidence.all)


programs = st.lists(
    st.sampled_from(
        [
            "{a}.",
            "{b}.",
            "c :- a.",
            "d :- not a.",
            ":- a, b.",
            "e :- c, d.",
            "{f} :- b.",
            "-g :- a.",
        ]
    ),
    min_size=1,
    max_size=6,
).map(" ".join)


@settings(max_examples=40, deadline=None)
@given(programs, st.sampled_from(Mode))
def test_the_native_consequences_equal_those_derived_from_the_enumerated_models(
    text: str, mode: Mode
) -> None:
    grounded = ground(Program(text))
    assert not isinstance(grounded, Fault)
    enumerated = grounded.solve()
    native = grounded.consequences(mode)
    match enumerated:
        case Consistent(models, Exhausted.EXHAUSTED):
            view = world_view(Consistent(models, Exhausted.EXHAUSTED))
            assert not isinstance(view, Truncation)
            expected = view.cautious if mode is Mode.CAUTIOUS else view.brave
            assert native == Consistent(Consequences(mode, expected), Exhausted.EXHAUSTED)
        case Inconsistent():
            assert native == enumerated
        case _:
            pytest.fail("a small program must be decided")


def test_a_show_of_numbers_and_strings_selects_no_literal() -> None:
    found = solve(Program('{p}. q. #show 42 : p. #show "s" : p. #show q : p. #show q/0.'))
    assert isinstance(found, Consistent)
    assert {m.shown for m in found.evidence.all} == {frozenset({Literal("q")})}


def test_a_refutation_is_minimal_not_merely_sufficient() -> None:
    scenario = frozenset({Assumption(P), Assumption(Q), Assumption(Literal("r"))})
    found = solve(Program("{p;q;r}. :- p, q."), scenario)
    assert found == Inconsistent(These(frozenset({Assumption(P), Assumption(Q)})))


def test_assumptions_are_not_to_blame_when_the_program_has_no_model_of_its_own() -> None:
    assert solve(Program("p. :- p."), frozenset({Assumption(Q)})) == Inconsistent(NotThese())


def test_a_refutation_cut_short_by_the_budget_is_not_called_minimal() -> None:
    grounded = ground(Program("{p;q;r}. :- p, q."))
    assert not isinstance(grounded, Fault)
    core = frozenset({Assumption(P), Assumption(Q), Assumption(Literal("r"))})
    cut = grounded._refutation(core, core, lambda: Truncation.BUDGET)  # noqa: SLF001
    assert cut == These(core, minimal=False)


scenarios = st.frozensets(
    st.builds(
        Assumption,
        st.sampled_from([Literal(name) for name in "abcdef"]),
        st.booleans(),
    ),
    max_size=5,
)


@settings(max_examples=60, deadline=None)
@given(programs, scenarios)
def test_every_refutation_clashes_and_every_proper_part_of_it_is_satisfiable(
    text: str, scenario: frozenset[Assumption]
) -> None:
    grounded = ground(Program(text))
    assert not isinstance(grounded, Fault)
    found = grounded.solve(scenario)
    if not isinstance(found, Inconsistent) or not isinstance(found.refutation, These):
        return
    core = found.refutation.core
    assert core <= scenario
    assert found.refutation.minimal
    assert isinstance(grounded.solve(core), Inconsistent)
    assert all(isinstance(grounded.solve(core - {a}), Consistent) for a in core)


def test_the_optimum_is_the_cost_of_the_optimal_models_and_those_are_all_found() -> None:
    grounded = ground(Program("{p;q}. :- not p, not q. #minimize { 1,p : p; 1,q : q }."))
    assert not isinstance(grounded, Fault)
    found = grounded.optimize()
    assert isinstance(found, Consistent)
    assert found.conclusion is Exhausted.EXHAUSTED
    assert isinstance(found.evidence, Optimum)
    assert found.evidence.cost == (1,)
    assert {m.atoms for m in found.evidence.models.all} == {frozenset({P}), frozenset({Q})}


def test_a_maximized_level_is_reported_as_the_minimized_sum_clingo_reports() -> None:
    grounded = ground(Program("{p;q}. #maximize { 1,p : p; 1,q : q }."))
    assert not isinstance(grounded, Fault)
    found = grounded.optimize()
    assert isinstance(found, Consistent)
    assert isinstance(found.evidence, Optimum)
    assert found.evidence.cost == (-2,)


def test_levels_are_ordered_highest_priority_first() -> None:
    grounded = ground(Program("{p;q}. #minimize { 1@2 : p }. #minimize { 1@1 : q }."))
    assert not isinstance(grounded, Fault)
    found = grounded.optimize(frozenset({Assumption(Q)}))
    assert isinstance(found, Consistent)
    assert isinstance(found.evidence, Optimum)
    assert found.evidence.cost == (0, 1)


def test_with_no_objective_every_model_is_optimal() -> None:
    grounded = ground(Program("{p;q}."))
    assert not isinstance(grounded, Fault)
    found = grounded.optimize()
    assert isinstance(found, Consistent)
    assert isinstance(found.evidence, Optimum)
    assert (found.evidence.cost, len(found.evidence.models.all)) == ((), 4)


def test_the_model_cap_of_an_optimization_counts_optimal_models_only() -> None:
    grounded = ground(Program("{p;q}. :- not p, not q. #minimize { 1,p : p; 1,q : q }."))
    assert not isinstance(grounded, Fault)
    found = grounded.optimize(limits=Limits(models=1))
    assert isinstance(found, Consistent)
    assert found.conclusion is Truncation.TARGET
    assert isinstance(found.evidence, Optimum)
    assert len(found.evidence.models.all) == 1


def test_an_optimization_of_an_inconsistent_program_is_inconsistent() -> None:
    grounded = ground(Program("p. :- p. #minimize { 1 : p }."))
    assert not isinstance(grounded, Fault)
    assert grounded.optimize() == Inconsistent(NoAssumptions())


def test_an_optimization_under_a_scenario_optimizes_among_the_models_it_admits() -> None:
    grounded = ground(Program("{p;q}. #minimize { 1@2 : p }. #minimize { 1@1 : q }."))
    assert not isinstance(grounded, Fault)
    found = grounded.optimize(frozenset({Assumption(P)}))
    assert isinstance(found, Consistent)
    assert isinstance(found.evidence, Optimum)
    assert found.evidence.cost == (1, 0)


def test_an_interrupted_optimization_is_inconclusive() -> None:
    grounded = ground(Program("{p}. #minimize { 1 : p }."))
    assert not isinstance(grounded, Fault)
    stop = Interrupt()
    stop.pull()
    assert grounded.optimize(interrupt=stop) == Inconclusive(Truncation.INTERRUPTED)


def test_the_unproven_best_so_far_is_an_incumbent_and_closes_no_optimal_view() -> None:
    found = Consistent(Incumbent(Model(frozenset(), frozenset())), Truncation.BUDGET)
    assert optimal_view(found) is Truncation.BUDGET
    with pytest.raises(ValueError, match="proven"):
        optimal_view(Consistent(Incumbent(Model(frozenset(), frozenset())), Exhausted.EXHAUSTED))
