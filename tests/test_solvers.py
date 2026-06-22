"""``solvers`` — the clingo facade and the Mode→``Determination`` lowering (spec §3, §6, §9).

These run real clingo (fast; tiny programs). They confirm the facade produces the three-arm
``Determination``: a per-mode ``Consistent`` shape on SAT, ``Inconsistent`` on the whole-result
``unsatisfiable`` bit (§9.7), ``Inconclusive`` on a hit time budget (§7a). The keystone's **GATING**
property — ``type(solve(mode)) is shape_for(mode)`` and its readable fields are exactly
``populates(mode)`` — closes the accessor seam's second premise empirically (the postcondition).
"""

from pathlib import Path

import pytest
from clingo import Function, Symbol

from elenctic.result import (
    Consistent,
    ConsistentBrave,
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimalEnumeration,
    ConsistentOptimum,
    ConsistentWitness,
    Field,
    HarnessError,
    Inconclusive,
    Inconsistent,
    Observable,
    SeamError,
    brave_of,
    cautious_of,
    observables_of,
    optimal_observables_of,
    optimum_of,
    shown_census_of,
    shown_optimal_census_of,
    witness_of,
)
from elenctic.run import Mode, populates, shape_for
from elenctic.solvers import run_clingo, solve

_CHOICE = "1 {a; b} 1. #show a/0. #show b/0."  # answer sets {a}, {b}
_CHOICE_WITH_FACT = "1 {a; b} 1. c. #show a/0. #show b/0. #show c/0."  # ⋂={c}, ⋃={a,b,c}
_MINIMIZE = "1 {a; b} 1. #minimize { 1,a : a; 1,b : b }. #show a/0. #show b/0."  # two co-optimal


def names(symbols: frozenset[Symbol]) -> frozenset[str]:
    return frozenset(symbol.name for symbol in symbols)


def shown_names(observables: tuple[Observable, ...]) -> set[frozenset[str]]:
    return {names(o.shown) for o in observables}


def _write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text)
    return path


# --- the per-mode Consistent shapes (the SAT arm) ---


def test_default_mode_yields_a_consistent_witness() -> None:
    det = run_clingo(Mode.DEFAULT, "a. b. #show a/0. #show b/0.")
    assert isinstance(det, ConsistentWitness)
    assert names(witness_of(det).shown) == {"a", "b"}


def test_enum_all_collects_distinct_observables_and_derives_consequences() -> None:
    det = run_clingo(Mode.ENUM_ALL, _CHOICE)
    assert isinstance(det, ConsistentEnumeration)
    assert shown_names(observables_of(det)) == {frozenset({"a"}), frozenset({"b"})}
    assert names(brave_of(det)) == {"a", "b"}  # ⋃ derived from the census
    assert cautious_of(det) == frozenset()  # ⋂ empty: no atom in every model


def test_cautious_all_yields_the_cautious_consequences() -> None:
    det = run_clingo(Mode.CAUTIOUS_ALL, _CHOICE_WITH_FACT)
    assert isinstance(det, ConsistentCautious)
    assert names(cautious_of(det)) == {"c"}


def test_brave_all_yields_the_brave_consequences() -> None:
    det = run_clingo(Mode.BRAVE_ALL, _CHOICE_WITH_FACT)
    assert isinstance(det, ConsistentBrave)
    assert names(brave_of(det)) == {"a", "b", "c"}


def test_optimal_enum_yields_the_optimal_class_and_proven_optimum() -> None:
    det = run_clingo(Mode.OPTIMAL_ENUM, _MINIMIZE)
    assert isinstance(det, ConsistentOptimalEnumeration)
    assert optimum_of(det).cost == (1,)
    assert shown_names(optimal_observables_of(det)) == {frozenset({"a"}), frozenset({"b"})}


def test_optimal_yields_only_the_proven_optimum_cost() -> None:
    det = run_clingo(Mode.OPTIMAL, "1 {a; b} 1. #minimize { 2,a : a; 1,b : b }. #show a/0.")
    assert isinstance(det, ConsistentOptimum)
    assert optimum_of(det).cost == (1,)  # choosing b (cost 1) over a (cost 2)


def test_optimum_cost_vector_is_priority_ordered_highest_first() -> None:
    # Multi-level: level 2 (higher priority) before level 1 in the vector (spec §2.0).
    det = run_clingo(Mode.OPTIMAL, "a. b. #minimize { 2@2,a : a; 3@1,b : b }.")
    assert isinstance(det, ConsistentOptimum)
    assert optimum_of(det).cost == (2, 3)


# --- the Inconsistent arm: the whole-result bit, never an empty field (§9.7) ---


@pytest.mark.parametrize("mode", list(Mode), ids=lambda mode: mode.name)
def test_unsat_program_is_inconsistent_under_every_mode(mode: Mode) -> None:
    # "a. :- a." is UNSAT under every mode (incl. the optimization modes: an UNSAT optimization
    # reports unsatisfiable with no cost-bearing model, so the arm is decided before _optimum_cost).
    det = run_clingo(mode, "a. :- a.")
    assert isinstance(det, Inconsistent)


def test_unsat_program_is_inconsistent_under_clingcon() -> None:
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    assert isinstance(run_clingcon(Mode.ENUM_ALL, "a. :- a."), Inconsistent)


# --- the #maximize deferral: rejected at discovery; the raw facade behaviour pinned (a canary) ---


def test_maximize_cost_is_negated_at_the_facade_the_deferred_normalisation_canary() -> None:
    # spec §2.0 wants @cost's NATURAL value; clingo reports a #maximize cost negated (§9.1 spike).
    # v1 rejects @cost-over-#maximize at discovery, so this only pins the raw facade behaviour —
    # the canary that fails the day sign-normalisation lands.
    det = run_clingo(Mode.OPTIMAL, "1 {a; b} 1. #maximize { 3,a : a; 1,b : b }. #show a/0.")
    assert isinstance(det, ConsistentOptimum)
    assert optimum_of(det).cost == (-3,)  # maximizing picks a (value 3); internal cost is -3


def test_optimization_mode_on_a_nonoptimizing_program_raises_harness_error() -> None:
    # The _optimum_cost backstop is reachable if the discovery optimization precondition is bypassed
    # (a direct facade call on a #minimize-free program); it must fail loud, never fabricate a cost.
    with pytest.raises(HarnessError, match=r"no cost vector"):
        run_clingo(Mode.OPTIMAL, "a. #show a/0.")


# --- the Inconclusive arm: a hit budget is UNDECIDED, never FAIL/UNSAT (§7a) ---


def test_timeout_yields_inconclusive() -> None:
    # 2^30 models with a zero budget: the solve cannot finish, so the result is Inconclusive.
    det = run_clingo(Mode.ENUM_ALL, "{ p(1..30) }. #show p/1.", budget=0.0)
    assert isinstance(det, Inconclusive)


def test_clingo_enumeration_projects_so_a_hidden_blowup_still_decides() -> None:
    # clingo enumeration projects onto shown atoms (information-preserving), so a program with an
    # astronomically large hidden space but a single shown class decides instead of timing out:
    # 2^30 hidden p-subsets all project to the one shown class { s }, enumerated as a single model.
    det = run_clingo(Mode.ENUM_ALL, "{ p(1..30) }. s. #show s/0.", budget=5.0)
    assert isinstance(det, ConsistentEnumeration)  # decided, not Inconclusive
    assert shown_names(observables_of(det)) == {frozenset({"s"})}  # the single shown class


# --- THE GATING property: the lowering postcondition (the seam's second premise) ---

_ACCESSORS = {
    Field.WITNESS: witness_of,
    Field.SHOWN_CENSUS: shown_census_of,
    Field.FULL_CENSUS: observables_of,
    Field.CAUTIOUS: cautious_of,
    Field.BRAVE: brave_of,
    Field.SHOWN_OPTIMAL_CENSUS: shown_optimal_census_of,
    Field.FULL_OPTIMAL_CENSUS: optimal_observables_of,
    Field.OPTIMUM: optimum_of,
}

_SAT_PROGRAM = {
    Mode.DEFAULT: "a. #show a/0.",
    Mode.ENUM_ALL: _CHOICE,
    Mode.CAUTIOUS_ALL: _CHOICE_WITH_FACT,
    Mode.BRAVE_ALL: _CHOICE_WITH_FACT,
    Mode.OPTIMAL_ENUM: _MINIMIZE,
    Mode.OPTIMAL: _MINIMIZE,
}


def _readable_fields(shape: Consistent) -> frozenset[Field]:
    """The fields an accessor returns on ``shape`` without tripping the narrowing seam."""
    readable: set[Field] = set()
    for field, accessor in _ACCESSORS.items():
        try:
            accessor(shape)
        except SeamError:
            continue
        readable.add(field)
    return frozenset(readable)


@pytest.mark.parametrize("project", [False, True], ids=["no-project", "project"])
@pytest.mark.parametrize("solver", ["clingo", "clingcon"])
@pytest.mark.parametrize("mode", list(Mode), ids=lambda mode: mode.name)
def test_lowering_postcondition(solver: str, mode: Mode, project: bool) -> None:
    # The merge-gating property over BOTH backends × the projection coordinate: solvers produces,
    # for a SAT run of (mode, project), exactly shape_for(mode, projects_to_shown), whose readable
    # fields are exactly populates(mode, projects_to_shown), with projects_to_shown = project and a
    # theory solver.
    if solver == "clingcon":
        pytest.importorskip("clingcon")
    projects_to_shown = project and solver == "clingcon"
    det = solve(solver, mode, _SAT_PROGRAM[mode], project=project)
    assert isinstance(det, Consistent)
    assert type(det) is shape_for(mode, projects_to_shown)
    assert _readable_fields(det) == populates(mode, projects_to_shown)


# --- the clingcon facade: the theory half of the observable (§6.3) and registry dispatch ---


def test_clingcon_recovers_a_compound_csp_assignment() -> None:
    # send-money style: `#show.` so the answer lives entirely in the CSP assignment (§6.3).
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    det = run_clingcon(Mode.ENUM_ALL, "&dom {0..9} = digit(s). &sum { digit(s) } = 9. #show.")
    assert isinstance(det, ConsistentEnumeration)
    (observable,) = observables_of(det)
    assert observable.shown == frozenset()  # nothing shown; distinctness is the assignment
    assert (Function("digit", [Function("s")]), 9) in observable.assign


def test_clingcon_surfaces_distinct_csp_solutions_as_distinct_observables() -> None:
    # §9.3: distinct CSP assignments are distinct observables — the facade must never --project.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    det = run_clingcon(Mode.ENUM_ALL, "&dom {1..3} = v(x). #show.")
    assert isinstance(det, ConsistentEnumeration)
    observables = observables_of(det)
    assert len(observables) == 3  # not collapsed to 1 by projection
    assert {value for o in observables for _, value in o.assign} == {1, 2, 3}


def test_solve_dispatches_by_solver_name() -> None:
    pytest.importorskip("clingcon")
    clingo_det = solve("clingo", Mode.DEFAULT, "a. #show a/0.")
    clingcon_det = solve("clingcon", Mode.ENUM_ALL, "&dom {1..2} = v(x). #show.")
    assert isinstance(clingo_det, ConsistentWitness)
    assert isinstance(clingcon_det, ConsistentEnumeration)
    assert len(observables_of(clingcon_det)) == 2


def test_solve_rejects_an_unknown_solver() -> None:
    with pytest.raises(ValueError, match=r"unknown solver 'dlv'"):
        solve("dlv", Mode.DEFAULT, "a.")


def test_clingcon_timeout_yields_inconclusive() -> None:
    # The §9.5 "both backends" obligation: clingcon shares the _drive timeout path with clingo.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    det = run_clingcon(Mode.ENUM_ALL, "{ p(1..30) }. #show p/1.", budget=0.0)
    assert isinstance(det, Inconclusive)


# --- multi-file loading (the corpus loads encoding + instance; clingcon rewrites each, §6.2) ---


def test_run_clingo_loads_multiple_files_in_order(tmp_path: Path) -> None:
    encoding = _write(tmp_path, "enc.lp", "b :- a. #show b/0.\n")  # b follows from a
    instance = _write(tmp_path, "inst.lp", "a.\n")  # supplied by the instance
    det = run_clingo(Mode.DEFAULT, files=(encoding, instance))
    assert isinstance(det, ConsistentWitness)
    assert names(witness_of(det).shown) == {"b"}


def test_run_clingcon_rewrites_multiple_files(tmp_path: Path) -> None:
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    encoding = _write(tmp_path, "enc.lp", "&dom {1..3} = v. #show.\n")
    instance = _write(tmp_path, "inst.lp", "&sum { v } = 2.\n")  # theory atom in a second file
    det = run_clingcon(Mode.ENUM_ALL, files=(encoding, instance))
    assert isinstance(det, ConsistentEnumeration)
    (observable,) = observables_of(det)
    assert (Function("v"), 2) in observable.assign
