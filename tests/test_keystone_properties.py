"""Cross-cutting verification families for the field-compatibility keystone (spec §3, §5, §7a).

The per-module suites pin each layer; these tie the keystone together at the seam between layers:

- **populates ↔ shape (seam soundness).** For each mode, ``populates(mode)`` equals exactly the
  fields its ``Consistent`` shape makes readable through the accessor seam — an accessor returns iff
  the field is populated, else ``SeamError``. (The lowering contract's shape, the seam's premise 2.)
- **reads-honesty / no-seam-on-route.** Every check ``runs_for`` produces, run on the minimal shape
  of the mode it rides, returns a definite verdict and never ``SeamError``s — i.e. each check's
  declared ``reads`` really are the fields its ``_decide`` touches, and the wiring rule routed it to
  a mode that populates them.
- **arm-agnostic ``@expect`` (the false-PASS fence).** ``@expect sat`` reads ∅, so it PASSes on
  *any* ``Consistent`` shape (never a false-FAIL from an emptiness read); ``@expect unsat`` PASSes
  *only* on ``Inconsistent`` (never a false-PASS from ``observables == ()``).
"""

import pytest
from clingo import Function

from elenctic.checks import expect_sat, expect_unsat
from elenctic.expectation import parse
from elenctic.result import (
    Consistent,
    ConsistentBrave,
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimalEnumeration,
    ConsistentOptimum,
    ConsistentShownCensus,
    ConsistentShownOptimalCensus,
    ConsistentWitness,
    Field,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
    SeamError,
    Verdict,
    brave_of,
    cautious_of,
    observables_of,
    optimal_observables_of,
    optimum_of,
    shown_census_of,
    shown_optimal_census_of,
    witness_of,
)
from elenctic.run import Mode, populates, runs_for, shape_for


def _obs(*names: str) -> Observable:
    return Observable(frozenset(Function(n) for n in names))


# A minimal Consistent shape for each (mode, projects_to_shown), with the fields it makes readable.
_MODE_SHAPES: list[tuple[Mode, bool, Consistent, frozenset[Field]]] = [
    (Mode.DEFAULT, False, ConsistentWitness(_obs("a")), frozenset({Field.WITNESS})),
    (
        Mode.ENUM_ALL,
        False,
        ConsistentEnumeration((_obs("a"),)),
        frozenset({Field.SHOWN_CENSUS, Field.FULL_CENSUS, Field.CAUTIOUS, Field.BRAVE}),
    ),
    (
        Mode.ENUM_ALL,
        True,
        ConsistentShownCensus(frozenset({frozenset({Function("a")})})),
        frozenset({Field.SHOWN_CENSUS, Field.CAUTIOUS, Field.BRAVE}),
    ),
    (Mode.CAUTIOUS_ALL, False, ConsistentCautious(frozenset()), frozenset({Field.CAUTIOUS})),
    (Mode.BRAVE_ALL, False, ConsistentBrave(frozenset()), frozenset({Field.BRAVE})),
    (
        Mode.OPTIMAL_ENUM,
        False,
        ConsistentOptimalEnumeration((_obs("a"),), Optimum((0,))),
        frozenset({Field.SHOWN_OPTIMAL_CENSUS, Field.FULL_OPTIMAL_CENSUS, Field.OPTIMUM}),
    ),
    (
        Mode.OPTIMAL_ENUM,
        True,
        ConsistentShownOptimalCensus(frozenset({frozenset({Function("a")})}), Optimum((0,))),
        frozenset({Field.SHOWN_OPTIMAL_CENSUS, Field.OPTIMUM}),
    ),
    (Mode.OPTIMAL, False, ConsistentOptimum(Optimum((0,))), frozenset({Field.OPTIMUM})),
]

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

# The non-projecting (full) shape per mode, for the reads-honesty check below: the routed checks in
# this module's contracts are non-projecting, so they read the full tokens.
_MINIMAL_SHAPE = {mode: shape for mode, projects, shape, _ in _MODE_SHAPES if not projects}


def test_populates_matches_each_modes_shape_via_the_accessor_seam() -> None:
    # populates(mode, projects) == the fields the mode's shape exposes; an accessor returns iff the
    # field is populated, else SeamError (the lowering postcondition the accessor seam relies on).
    covered = {(mode, projects) for mode, projects, _, _ in _MODE_SHAPES}
    assert {mode for mode, _ in covered} == set(Mode)  # every mode covered
    assert {(Mode.ENUM_ALL, True), (Mode.OPTIMAL_ENUM, True)} <= covered  # both projected shapes
    for mode, projects, shape, fields in _MODE_SHAPES:
        assert type(shape) is shape_for(mode, projects)  # the Mode→shape arrow solvers.py honours
        assert populates(mode, projects) == fields
        for field, accessor in _ACCESSORS.items():
            if field in fields:
                accessor(shape)  # readable — no SeamError
            else:
                with pytest.raises(SeamError):
                    accessor(shape)


# Contracts chosen so runs_for exercises all six modes (DEFAULT and OPTIMAL need their own).
_CONTRACTS = [
    (
        "% @expect sat\n% @model { a }\n% @count 2\n% @assign { x=1 }\n% @cautious { a }\n"
        "% @brave { a }\n% @optimal { a }\n% @cautious optimal { a }\n% @brave optimal { a }\n"
        "% @count optimal 1\n% @cost { 8 }\n% @query yes { a }\n% @query no { a, b }\n"
        "% @query unknown { p(X) } = { a }\n"
    ),
    "% @expect unsat\n",  # DEFAULT
    "% @expect sat\n% @cost { 8 }\n",  # OPT (no optimal base) + DEFAULT
]


@pytest.mark.parametrize("contract", _CONTRACTS)
def test_correctly_routed_checks_read_cleanly(contract: str) -> None:
    # reads-honesty: every routed check, on the minimal shape of the mode it rides, yields a
    # definite verdict and never SeamErrors — the seam fires only on a misroute, which the wiring
    # rule forbids.
    for run in runs_for(parse(contract)):
        shape = _MINIMAL_SHAPE[run.mode]
        for check in run.checks:
            report = check(shape)  # raises SeamError if the check reads a field the shape lacks
            assert report.verdict in {Verdict.PASS, Verdict.FAIL, Verdict.UNDECIDED}


def test_expect_sat_is_mode_agnostic() -> None:
    # @expect sat reads ∅: PASS on EVERY Consistent shape (no emptiness-read false-FAIL), including
    # the projected shapes.
    for _mode, _projects, shape, _fields in _MODE_SHAPES:
        assert expect_sat()(shape).verdict is Verdict.PASS
    assert expect_sat()(Inconsistent()).verdict is Verdict.FAIL
    assert expect_sat()(Inconclusive()).verdict is Verdict.UNDECIDED


def test_expect_unsat_passes_only_on_inconsistent() -> None:
    # The headline false-PASS fence: @expect unsat PASSes on the Inconsistent arm alone — never from
    # reading observables == () off a non-enumeration shape (the old silent-miscompile, now gone).
    assert expect_unsat()(Inconsistent()).verdict is Verdict.PASS
    assert expect_unsat()(ConsistentWitness(_obs("a"))).verdict is Verdict.FAIL  # rides DEFAULT
    assert expect_unsat()(Inconclusive()).verdict is Verdict.UNDECIDED
