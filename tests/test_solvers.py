"""``solvers`` — the clingo facade and the Mode→``Determination`` lowering.

These run real clingo (fast; tiny programs). They confirm the facade produces the three-arm
``Determination``: a per-mode ``Consistent`` shape on SAT, ``Inconsistent`` on the whole-result
``unsatisfiable`` bit, ``Inconclusive`` on a hit time budget. The **GATING**
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
    ConsistentShownCensus,
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
    # Multi-level: level 2 (higher priority) before level 1 in the vector.
    det = run_clingo(Mode.OPTIMAL, "a. b. #minimize { 2@2,a : a; 3@1,b : b }.")
    assert isinstance(det, ConsistentOptimum)
    assert optimum_of(det).cost == (2, 3)


# a collision program: {a} at cost (0,) is optimal, {b} at cost (1,) is sub-optimal, and both
# project to the same shown class { mark } (so a cross-level dedup loss would corrupt the class).
_COLLISION = "1 { a; b } 1. mark :- a. mark :- b. #minimize { 0,a : a; 1,b : b }. #show mark/0."


def test_optimal_enum_pins_the_collision_class_to_the_proven_optimum() -> None:
    # The two-phase optimal lowering pins the optimal class to { mark } at the proven optimum (0,),
    # regardless of the sub-optimal {b} -> {mark} collision sharing the shown projection. Robust by
    # construction: phase 2 enumerates a single optimization level, so no model below the optimum is
    # enumerable and cross-level deduplication cannot empty or corrupt the class.
    det = run_clingo(Mode.OPTIMAL_ENUM, _COLLISION)
    assert isinstance(det, ConsistentOptimalEnumeration)
    assert optimum_of(det).cost == (0,)
    assert shown_names(optimal_observables_of(det)) == {frozenset({"mark"})}


def test_optimal_enum_timeout_yields_inconclusive() -> None:
    # The two-phase optimal driver returns Inconclusive on a hit budget in EITHER phase, never a
    # fabricated or partial optimal class. A constant objective makes all 2^28 p-choices co-optimal,
    # so phase 2 (enumerating the optimal class) cannot finish at a 0.0 poll — Inconclusive holds
    # whether or not the trivially-fast phase 1 (prove c*) wins the wait(0.0) race. (A prior
    # `#minimize { 1,p(X) : p(X) }` made the optimum the empty model, found instantly, so the result
    # raced on phase 1 and flaked under suite load.)
    program = "{ p(1..28) }. c. #minimize { 1,c : c }. #show p/1."
    det = run_clingo(Mode.OPTIMAL_ENUM, program, budget=0.0)
    assert isinstance(det, Inconclusive)


def test_clingcon_optimal_enum_two_phase_yields_the_optimal_class() -> None:
    # The clingcon OPTIMAL_ENUM path is two-phase too (prove c*, then enumerate at enum,c*); confirm
    # the optimum and the optimal class over a #minimize the facade reads the same way as clingo.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    program = "1 {a; b} 1. #minimize { 2,a : a; 1,b : b }. #show a/0. #show b/0."
    det = run_clingcon(Mode.OPTIMAL_ENUM, program)
    assert isinstance(det, ConsistentOptimalEnumeration)
    assert optimum_of(det).cost == (1,)  # choosing b (cost 1) over a (cost 2)
    assert shown_names(optimal_observables_of(det)) == {frozenset({"b"})}


# --- the Inconsistent arm: the whole-result bit, never an empty field ---


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
    # @cost wants the NATURAL value; clingo reports a #maximize cost negated.
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


# --- the Inconclusive arm: a hit budget is UNDECIDED, never FAIL/UNSAT ---


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


# --- projection: the decoupling of project (the flag) from projects_to_shown (the shape) ---


def test_clingo_projects_but_yields_the_full_shape() -> None:
    # The decoupling: clingo @count over ENUM_ALL passes --project (perf) yet yields the FULL shape
    # (assign ≡ ∅, so --project is information-preserving), read correctly — clingo is unaffected.
    det = solve("clingo", Mode.ENUM_ALL, _CHOICE, project=True)
    assert isinstance(det, ConsistentEnumeration)  # the full shape, despite --project
    assert len(observables_of(det)) == 2  # {a}, {b}


def test_clingcon_projects_to_the_shown_shape_when_no_full_reader() -> None:
    # A projecting clingcon enumeration collapses CSP multiplicity onto the shown census (the
    # shown-only shape), so a shown-only contract terminates instead of enumerating the CSP space.
    pytest.importorskip("clingcon")
    det = solve("clingcon", Mode.ENUM_ALL, "&dom {1..3} = v(x). ok. #show ok/0.", project=True)
    assert isinstance(det, ConsistentShownCensus)
    assert shown_census_of(det) == {frozenset({Function("ok")})}  # 3 CSP solutions -> 1 shown class


def test_clingcon_stays_full_when_project_is_off() -> None:
    # project=False keeps the full census (3 distinct CSP observables): the multiplicity a @count
    # or @assign rider needs is preserved.
    pytest.importorskip("clingcon")
    det = solve("clingcon", Mode.ENUM_ALL, "&dom {1..3} = v(x). #show.", project=False)
    assert isinstance(det, ConsistentEnumeration)
    assert len(observables_of(det)) == 3


# --- the clingcon facade: the theory half of the observable and registry dispatch ---


def test_clingcon_recovers_a_compound_csp_assignment() -> None:
    # send-money style: `#show.` so the answer lives entirely in the CSP assignment.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    det = run_clingcon(Mode.ENUM_ALL, "&dom {0..9} = digit(s). &sum { digit(s) } = 9. #show.")
    assert isinstance(det, ConsistentEnumeration)
    (observable,) = observables_of(det)
    assert observable.shown == frozenset()  # nothing shown; distinctness is the assignment
    assert (Function("digit", [Function("s")]), 9) in observable.assign


def test_clingcon_surfaces_distinct_csp_solutions_as_distinct_observables() -> None:
    # distinct CSP assignments are distinct observables — the facade must never --project.
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
    # The "both backends" obligation: clingcon shares the _drive timeout path with clingo.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    det = run_clingcon(Mode.ENUM_ALL, "{ p(1..30) }. #show p/1.", budget=0.0)
    assert isinstance(det, Inconclusive)


# --- multi-file loading (the corpus loads encoding + instance; clingcon rewrites each) ---


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


def test_run_clingo_resolves_include_relative_to_the_case_file(tmp_path: Path) -> None:
    # The loader must use Control.load (resolves #include relative to the including file), not
    # read_text+add (which never resolves the directive). A case includes a sibling library.
    (tmp_path / "lib").mkdir()
    _write(tmp_path / "lib", "facts.lp", "p(1). p(2).\n")
    case = _write(tmp_path, "case.lp", '#include "lib/facts.lp".\nq :- p(1).\n#show q/0.\n')
    det = run_clingo(Mode.ENUM_ALL, files=(case,))
    assert isinstance(det, ConsistentEnumeration)
    assert any("q" in names(obs.shown) for obs in observables_of(det))


def test_run_clingcon_rewrites_theory_inside_an_include(tmp_path: Path) -> None:
    # parse_files fires the theory rewrite on the EXPANDED AST: a theory constraint living entirely
    # in an #include'd library is rewritten and propagated (spike b1), not merely path-resolved.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    (tmp_path / "lib").mkdir()
    _write(tmp_path / "lib", "sched.lp", "&dom { 1..3 } = x. &sum { x } >= 2.\n")  # x in {2,3}
    case = _write(tmp_path, "case.lp", '#include "lib/sched.lp".\n#show.\n')
    det = run_clingcon(Mode.ENUM_ALL, files=(case,))
    assert isinstance(det, ConsistentEnumeration)
    xs = {val for obs in observables_of(det) for sym, val in obs.assign if str(sym) == "x"}
    assert xs == {2, 3}  # the included &dom/&sum BOTH rewrote and propagated (x=1 pruned)


def test_run_clingo_suppresses_clingo_diagnostics_on_stderr(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # clingo logs "atom does not occur in any rule head" for a body-only atom; the solve facade
    # captures clingo's logger (as program.inspect does) so it never leaks to stderr. elenctic owns
    # its diagnostics; a genuine ground/solve error still raises, unaffected by the logger.
    run_clingo(Mode.ENUM_ALL, program="p :- q. #show p/0.")
    assert "does not occur" not in capfd.readouterr().err


def test_run_clingcon_suppresses_solver_diagnostics_on_stderr(
    capfd: pytest.CaptureFixture[str],
) -> None:
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    run_clingcon(Mode.ENUM_ALL, program="p :- q. #show p/0.")
    assert "does not occur" not in capfd.readouterr().err
