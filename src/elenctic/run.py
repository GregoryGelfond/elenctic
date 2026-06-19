"""``runs_for``: derive the solver runs (and their checks) a contract requires (spec §3, §4).

A :class:`Run` is one solve configuration plus the self-describing checks (dx#9 / option C) that
read its result; tags that can share a configuration coalesce onto one run, while the genuinely
different searches (brave vs cautious vs optimisation vs full enumeration) stay separate.
``runs_for`` is **pure**: it reads the :class:`~elenctic.expectation.Expectation` and constructs
runs; only ``solvers.py`` ever touches a solver.

The run-configuration taxonomy is fixed (Global Constraints / spec §3). The canonical arg tuples are
solver-agnostic; ``--project`` is the clingo facade's business (§6.1), never added here.
"""

from dataclasses import dataclass
from typing import Final, assert_never

from elenctic import checks
from elenctic.checks import Check
from elenctic.expectation import Expectation, Sat, Unsat
from elenctic.query import Answer, BindingQuery, GroundQuery, Query

DEFAULT: Final[tuple[str, ...]] = ()
ENUM_ALL: Final[tuple[str, ...]] = ("--models=0",)
BRAVE_ALL: Final[tuple[str, ...]] = ("--enum-mode=brave", "--models=0")
CAUTIOUS_ALL: Final[tuple[str, ...]] = ("--enum-mode=cautious", "--models=0")
OPT_ENUM: Final[tuple[str, ...]] = ("--opt-mode=optN", "--models=0")
OPT: Final[tuple[str, ...]] = ("--opt-mode=opt",)

TAXONOMY: Final[frozenset[tuple[str, ...]]] = frozenset(
    {DEFAULT, ENUM_ALL, BRAVE_ALL, CAUTIOUS_ALL, OPT_ENUM, OPT}
)


@dataclass(frozen=True, slots=True, eq=False)
class Run:
    """One solve configuration and the checks reading its result (spec §3, §4).

    ``args`` is the canonical, solver-agnostic arg tuple of one taxonomy cell; ``checks`` are the
    per-tag checks coalesced onto this one solve, each carrying its own contract-tag label (dx#9),
    so a run is fully described — and explainable — before any solve. Equality is by identity
    (``eq=False``, matching ``Check``): compare ``run.args`` / ``check.label``, not ``==``.
    """

    args: tuple[str, ...]
    checks: tuple[Check, ...]


def runs_for(exp: Expectation) -> tuple[Run, ...]:
    """Derive the coalesced runs an expectation requires (pure, spec §3, §4)."""
    match exp:
        case Unsat():
            return (Run(DEFAULT, (checks.expect_unsat(),)),)
        case Sat():
            return _sat_runs(exp)
        case _:
            assert_never(exp)


def _sat_runs(exp: Sat) -> tuple[Run, ...]:
    """Coalesce a satisfiable contract's tags onto the run-configuration taxonomy (spec §3, §4).

    Output order is deterministic: ``bucket`` is insertion-ordered and the add-sequence is fixed.
    Coalescing-soundness invariant: each check is added under a config that populates the
    ``SolveResult`` fields its decision reads — the enumeration modes + ``@expect`` under
    ``ENUM_ALL``, ``@cautious``/ground-``@query`` under ``CAUTIOUS_ALL`` (⋂), ``@brave`` under
    ``BRAVE_ALL`` (⋃), the optimal modes under ``OPT_ENUM``. The ``checks.py`` totality guards are
    the belt-and-suspenders if a route ever goes stale; lifting ``reads(check) ⊆ populates(config)``
    into the types is the parked keystone (see reserved-and-deferred.md).
    """
    bucket: dict[tuple[str, ...], list[Check]] = {}

    def add(config: tuple[str, ...], check: Check) -> None:
        bucket.setdefault(config, []).append(check)

    if exp.model is not None:
        add(ENUM_ALL, checks.has_model(exp.model))
    if exp.count is not None:
        add(ENUM_ALL, checks.count_is(exp.count))
    if exp.assign is not None:
        add(ENUM_ALL, checks.assign_contains(exp.assign))
    if exp.cautious:
        add(CAUTIOUS_ALL, checks.cautious_contains(exp.cautious))
    if exp.brave:
        add(BRAVE_ALL, checks.brave_contains(exp.brave))

    if exp.optimal_model is not None:
        add(OPT_ENUM, checks.has_optimal_model(exp.optimal_model))
    if exp.cautious_optimal:
        add(OPT_ENUM, checks.cautious_optimal_contains(exp.cautious_optimal))
    if exp.brave_optimal:
        add(OPT_ENUM, checks.brave_optimal_contains(exp.brave_optimal))
    if exp.count_optimal is not None:
        add(OPT_ENUM, checks.count_optimal_is(exp.count_optimal))
    if exp.cost is not None:
        add(OPT_ENUM if _has_optimal_base(exp) else OPT, checks.cost_is(exp.cost))

    for query in exp.queries:
        add(_query_config(query), checks.query_matches(query))

    # @expect sat reads `observables`, so it rides an existing full enumeration when one exists,
    # else a cheap DEFAULT 1-model solve. It cannot ride CAUTIOUS_ALL / BRAVE_ALL / OPT_ENUM: those
    # populate only ⋂ / ⋃ / optimal_observables, never `observables` (the field expect_sat reads).
    # §7a edge: a timed-out ENUM_ALL reports UNDECIDED even with a model in hand — verdict-safe,
    # case-masked by co-located enumeration checks; existential-aware §7a is deferred (ledger).
    add(ENUM_ALL if ENUM_ALL in bucket else DEFAULT, checks.expect_sat())

    return tuple(Run(config, tuple(carried)) for config, carried in bucket.items())


def _has_optimal_base(exp: Sat) -> bool:
    """Whether any optimal-base mode is present, so @cost rides the shared ``OPT_ENUM`` enumeration
    of Opt(P) rather than a cheap single-optimum ``OPT`` solve (spec §3)."""
    return (
        exp.optimal_model is not None
        or bool(exp.cautious_optimal)
        or bool(exp.brave_optimal)
        or exp.count_optimal is not None
    )


def _query_config(query: Query) -> tuple[str, ...]:
    """The run a ``@query`` rides: ground and yes/no-binding queries read the cautious consequences
    ⋂ (``CAUTIOUS_ALL``); an ``unknown``-binding query also needs the brave ⋃, so it rides one full
    ``ENUM_ALL`` enumeration that yields both ⋂ and ⋃ off a single solve (spec §3 / §2.4)."""
    match query:
        case BindingQuery(answer=Answer.unknown):
            return ENUM_ALL
        case BindingQuery() | GroundQuery():
            return CAUTIOUS_ALL
        case _:
            assert_never(query)
