"""``runs_for``: derive the solver runs (and their checks) a contract requires (spec §3, §4).

A :class:`Run` is one solve configuration (:class:`Mode`) plus the self-describing checks (dx#9 /
option C) that read its result; tags that can share a configuration coalesce onto one run, while the
genuinely different searches (brave vs cautious vs optimisation vs full enumeration) stay separate.
``runs_for`` is **pure**: it reads the :class:`~elenctic.expectation.Expectation` and constructs
runs; only ``solvers.py`` ever touches a solver.

The wiring rule (Half B of the field-compatibility keystone): a check declares ``reads`` and a mode
``populates`` a field-set; ``Run.__post_init__`` asserts ``reads ⊆ populates(mode)`` per check, so a
stale route fails loud at plan construction (a :class:`~elenctic.result.HarnessError`), before any
solve — never as a costumed verdict.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Final, assert_never

from elenctic import checks
from elenctic.checks import Check
from elenctic.expectation import Expectation, Sat, Unsat
from elenctic.query import Query, QueryForm, classify
from elenctic.result import Field, HarnessError


class Mode(Enum):
    """One solve configuration of the fixed run-configuration taxonomy (spec §3). The taxonomy is
    solver-agnostic; ``args`` is its **clingo** lowering (the search-config flags this mode runs
    as). The facade adds output flags such as ``--project`` (§6.1); the explain surface names the
    mode itself, which another backend would lower differently."""

    DEFAULT = "default"
    ENUM_ALL = "enum-all"
    BRAVE_ALL = "brave-all"
    CAUTIOUS_ALL = "cautious-all"
    OPT_ENUM = "opt-enum"
    OPT = "opt"

    @property
    def args(self) -> tuple[str, ...]:
        """The clingo arg tuple this mode lowers to — its search-config flags (spec §3); another
        backend would lower the same mode differently."""
        return _ARGS[self]


_ARGS: Final[dict[Mode, tuple[str, ...]]] = {
    Mode.DEFAULT: (),
    Mode.ENUM_ALL: ("--models=0",),
    Mode.BRAVE_ALL: ("--enum-mode=brave", "--models=0"),
    Mode.CAUTIOUS_ALL: ("--enum-mode=cautious", "--models=0"),
    Mode.OPT_ENUM: ("--opt-mode=optN", "--models=0"),
    Mode.OPT: ("--opt-mode=opt",),
}

_POPULATES: Final[dict[Mode, frozenset[Field]]] = {
    Mode.DEFAULT: frozenset({Field.WITNESS}),
    Mode.ENUM_ALL: frozenset({Field.OBSERVABLES, Field.CAUTIOUS, Field.BRAVE}),
    Mode.BRAVE_ALL: frozenset({Field.BRAVE}),
    Mode.CAUTIOUS_ALL: frozenset({Field.CAUTIOUS}),
    Mode.OPT_ENUM: frozenset({Field.OPTIMAL_OBSERVABLES, Field.OPTIMUM}),
    Mode.OPT: frozenset({Field.OPTIMUM}),
}


def populates(mode: Mode) -> frozenset[Field]:
    """The fields a ``Consistent`` result of ``mode`` makes readable (total over ``Mode``). The
    lowering contract's postcondition for ``solvers.py`` (a ``Consistent`` of ``mode`` carries
    exactly these fields) is the seam's second unreachability premise (``result``)."""
    return _POPULATES[mode]


class RoutingError(HarnessError):
    """A check was paired with a run whose mode does not populate the fields it reads — the
    ``reads ⊆ populates`` wiring rule was violated at plan construction. A harness-internal bug (a
    stale route, or a mode added without updating ``populates``), never a contract or a verdict; the
    session reports it as a harness error, not a program-under-test failure."""


@dataclass(frozen=True, slots=True, eq=False)
class Run:
    """One solve configuration (:class:`Mode`) and the checks reading its result (spec §3, §4).

    The wiring rule is a property of a *valid* ``Run`` (Hoare), enforced at construction: a check
    whose ``reads`` exceed ``populates(mode)`` is rejected before any solve, naming the offending
    check, the missing fields, and the mode. Equality is by identity (``eq=False``, matching
    ``Check``): compare ``run.mode`` / ``check.label``, not ``==``.
    """

    mode: Mode
    checks: tuple[Check, ...]

    def __post_init__(self) -> None:
        provided = populates(self.mode)
        for check in self.checks:
            missing = check.reads - provided
            if missing:
                want = ", ".join(sorted(field.value for field in missing))
                have = ", ".join(sorted(field.value for field in provided))
                raise RoutingError(
                    f"{check.label} reads {{{want}}}, which {self.mode.name} populates only "
                    f"{{{have}}} — the reads ⊆ populates wiring rule is violated "
                    "(an elenctic bug, not a verdict)"
                )


def runs_for(exp: Expectation) -> tuple[Run, ...]:
    """Derive the coalesced runs an expectation requires (pure, spec §3, §4)."""
    match exp:
        case Unsat():
            return (Run(Mode.DEFAULT, (checks.expect_unsat(),)),)
        case Sat():
            return _sat_runs(exp)
        case _:
            assert_never(exp)


def _sat_runs(exp: Sat) -> tuple[Run, ...]:
    """Coalesce a satisfiable contract's tags onto the run-configuration taxonomy (spec §3, §4).

    Output order is deterministic: ``bucket`` is insertion-ordered and the add-sequence is fixed.
    Each check is added under a mode that populates the fields its decision reads; the wiring rule
    (``Run.__post_init__``) verifies ``reads ⊆ populates`` per run, so coalescing soundness is
    enforced by construction rather than by hand.
    """
    bucket: dict[Mode, list[Check]] = {}

    def add(mode: Mode, check: Check) -> None:
        bucket.setdefault(mode, []).append(check)

    # ``is not None`` for the Optional cells (absent vs present — @count 0 is a *present* unsat
    # claim, not absence); truthy for the containment tags, where ∅ is a vacuous claim their
    # builders reject (so empty == absent), keeping them consistent with cautious/brave.
    if exp.model is not None:
        add(Mode.ENUM_ALL, checks.has_model(exp.model))
    if exp.count is not None:
        add(Mode.ENUM_ALL, checks.count_is(exp.count))
    if exp.assign:
        add(Mode.ENUM_ALL, checks.assign_contains(exp.assign))
    # cautious and brave run as two native consequence solves, not one ENUM_ALL census: clingo's
    # --enum-mode=cautious/brave compute ⋂/⋃ directly, avoiding a full (possibly exponential) enum.
    if exp.cautious:
        add(Mode.CAUTIOUS_ALL, checks.cautious_contains(exp.cautious))
    if exp.brave:
        add(Mode.BRAVE_ALL, checks.brave_contains(exp.brave))

    if exp.optimal_model is not None:
        add(Mode.OPT_ENUM, checks.has_optimal_model(exp.optimal_model))
    if exp.cautious_optimal:
        add(Mode.OPT_ENUM, checks.cautious_optimal_contains(exp.cautious_optimal))
    if exp.brave_optimal:
        add(Mode.OPT_ENUM, checks.brave_optimal_contains(exp.brave_optimal))
    if exp.count_optimal is not None:
        add(Mode.OPT_ENUM, checks.count_optimal_is(exp.count_optimal))
    if exp.cost is not None:
        add(Mode.OPT_ENUM if _has_optimal_base(exp) else Mode.OPT, checks.cost_is(exp.cost))

    for query in exp.queries:
        add(_query_mode(query), checks.query_matches(query))

    # @expect sat reads ∅ (the arm is the answer), so it could ride any run; it rides an existing
    # full enumeration when one exists, else a cheap DEFAULT 1-model solve — deliberately not an
    # expensive cautious/brave/opt run, which is likelier to time out and report UNDECIDED where the
    # cheap solve would decide satisfiability. (Existential-aware §7a is deferred — ledger.)
    add(Mode.ENUM_ALL if Mode.ENUM_ALL in bucket else Mode.DEFAULT, checks.expect_sat())

    return tuple(Run(mode, tuple(carried)) for mode, carried in bucket.items())


def _has_optimal_base(exp: Sat) -> bool:
    """Whether any optimal-base mode is present, so @cost rides the shared ``OPT_ENUM`` enumeration
    of Opt(P) rather than a cheap single-optimum ``OPT`` solve (spec §3)."""
    return (
        exp.optimal_model is not None
        or bool(exp.cautious_optimal)
        or bool(exp.brave_optimal)
        or exp.count_optimal is not None
    )


def _query_mode(query: Query) -> Mode:
    """The run a ``@query`` rides (corrected Def 2.2.2), keyed on the shared ``query.classify`` so
    route and read never disagree. A *singleton* ground query and a yes/no binding read ⋂
    (``CAUTIOUS_ALL``); a *conjunctive* ground query needs the census (its "no" is ``∀M ∃i: l̄i∈M``,
    not a ⋂ property), and an ``unknown`` binding needs ⋃ too, so both ride a full enumeration
    (``ENUM_ALL``, which carries both ⋂ and ⋃; spec §3 / §2.4)."""
    form = classify(query)
    match form:
        case QueryForm.SINGLETON_GROUND | QueryForm.BINDING_SETTLED:
            return Mode.CAUTIOUS_ALL
        case QueryForm.CONJUNCTIVE_GROUND | QueryForm.BINDING_UNKNOWN:
            return Mode.ENUM_ALL
        case _:
            assert_never(form)
