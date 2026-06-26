"""``runs_for``: derive the solver runs (and their checks) a contract requires.

A :class:`Run` is one solve configuration (:class:`Mode`) plus the self-describing checks that read
its result; tags that can share a configuration coalesce onto one run, while the
genuinely different searches (brave vs cautious vs optimisation vs full enumeration) stay separate.
``runs_for`` is **pure**: it reads the :class:`~elenctic.expectation.Expectation` and constructs
runs; only ``solvers.py`` ever touches a solver.

The wiring rule (the field-compatibility invariant): a check declares ``reads`` and a mode
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
    HarnessError,
)


class Mode(Enum):
    """One solve configuration of the fixed run-configuration taxonomy. The taxonomy is
    solver-agnostic; ``args`` is its **clingo** lowering (the search-config flags this mode runs
    as). The facade adds output flags such as ``--project``; the explain surface names the
    mode itself, which another backend would lower differently."""

    DEFAULT = "default"
    ENUM_ALL = "enum-all"
    BRAVE_ALL = "brave-all"
    CAUTIOUS_ALL = "cautious-all"
    OPTIMAL_ENUM = "optimal-enum"
    OPTIMAL = "optimal"

    @property
    def args(self) -> tuple[str, ...]:
        """The clingo arg tuple this mode lowers to — its search-config flags; another
        backend would lower the same mode differently."""
        return _ARGS[self]


_ARGS: Final[dict[Mode, tuple[str, ...]]] = {
    Mode.DEFAULT: (),
    Mode.ENUM_ALL: ("--models=0",),
    Mode.BRAVE_ALL: ("--enum-mode=brave", "--models=0"),
    Mode.CAUTIOUS_ALL: ("--enum-mode=cautious", "--models=0"),
    Mode.OPTIMAL_ENUM: ("--opt-mode=optN", "--models=0"),
    Mode.OPTIMAL: ("--opt-mode=opt",),
}

_POPULATES: Final[dict[Mode, frozenset[Field]]] = {
    Mode.DEFAULT: frozenset({Field.WITNESS}),
    Mode.ENUM_ALL: frozenset({Field.SHOWN_CENSUS, Field.FULL_CENSUS, Field.CAUTIOUS, Field.BRAVE}),
    Mode.BRAVE_ALL: frozenset({Field.BRAVE}),
    Mode.CAUTIOUS_ALL: frozenset({Field.CAUTIOUS}),
    Mode.OPTIMAL_ENUM: frozenset(
        {Field.SHOWN_OPTIMAL_CENSUS, Field.FULL_OPTIMAL_CENSUS, Field.OPTIMUM}
    ),
    Mode.OPTIMAL: frozenset({Field.OPTIMUM}),
}

# The projection-sensitive (full-census) token each projecting mode SHEDS when it projects to shown:
# under a theory ``--project`` erases the multiplicity/assignment that token carries. Non-projecting
# modes are absent here, so the projection coordinate is a no-op for them.
_FULL_TOKEN: Final[dict[Mode, Field]] = {
    Mode.ENUM_ALL: Field.FULL_CENSUS,
    Mode.OPTIMAL_ENUM: Field.FULL_OPTIMAL_CENSUS,
}


def populates(mode: Mode, projects_to_shown: bool = False) -> frozenset[Field]:
    """The fields a ``Consistent`` result of ``(mode, projects_to_shown)`` makes readable (total). A
    projecting run sheds exactly its full-census token (multiplicity/assignment erased), keeping the
    shown view and the consequence views (both derivable from the shown set). The lowering
    postcondition for ``solvers.py`` — a ``Consistent`` of ``(mode, projects_to_shown)`` carries
    exactly these fields — is the accessor seam's second unreachability premise."""
    fields = _POPULATES[mode]
    if projects_to_shown and mode in _FULL_TOKEN:
        return fields - {_FULL_TOKEN[mode]}
    return fields


_SHAPE: Final[dict[Mode, type[Consistent]]] = {
    Mode.DEFAULT: ConsistentWitness,
    Mode.ENUM_ALL: ConsistentEnumeration,
    Mode.BRAVE_ALL: ConsistentBrave,
    Mode.CAUTIOUS_ALL: ConsistentCautious,
    Mode.OPTIMAL_ENUM: ConsistentOptimalEnumeration,
    Mode.OPTIMAL: ConsistentOptimum,
}

# The shown-only shape each projecting mode builds when projecting to shown (a theory phenomenon).
_PROJECTED_SHAPE: Final[dict[Mode, type[Consistent]]] = {
    Mode.ENUM_ALL: ConsistentShownCensus,
    Mode.OPTIMAL_ENUM: ConsistentShownOptimalCensus,
}


def shape_for(mode: Mode, projects_to_shown: bool = False) -> type[Consistent]:
    """The ``Consistent`` shape ``solvers.py`` must produce for ``(mode, projects_to_shown)`` — the
    source-level Mode→shape arrow of the lowering contract. A projecting run of a projecting mode
    builds the shown-only shape; everything else builds the full shape. The fields an instance makes
    readable through the accessor seam are exactly ``populates(mode, projects_to_shown)``; a seam
    test ties the two so the lowering postcondition cannot silently drift."""
    if projects_to_shown and mode in _PROJECTED_SHAPE:
        return _PROJECTED_SHAPE[mode]
    return _SHAPE[mode]


class RoutingError(HarnessError):
    """A check was paired with a run whose mode does not populate the fields it reads — the
    ``reads ⊆ populates`` wiring rule was violated at plan construction. A harness-internal bug (a
    stale route, or a mode added without updating ``populates``), never a contract or a verdict; the
    runner reports it as a harness error, not a program-under-test failure."""


@dataclass(frozen=True, slots=True, eq=False)
class Run:
    """One solve configuration (:class:`Mode`), the checks reading its result, and the projection
    state.

    ``project`` is the ``--project`` decision (:func:`should_project`); ``theory_in_force`` is
    whether a theory (CSP) solver runs it. ``projects_to_shown = project ∧ theory_in_force`` is the
    *shape collapse* — true only when projection erases information (a theory solver), so a
    projecting pure clingo run still yields the full shape (``--project`` is information-preserving
    there). The wiring rule is a property of a *valid* ``Run``, enforced at construction: a check
    whose ``reads`` exceed ``populates(mode, projects_to_shown)`` is rejected before any solve,
    naming the offending check, the missing fields, and the mode — so a ``should_project``
    mis-derive (a full-view reader on a projecting run) is a ``RoutingError`` here, before any
    solve, never a costumed verdict. Equality is by identity (``eq=False``, matching ``Check``):
    compare ``run.mode`` / ``check.label``, not ``==``.
    """

    mode: Mode
    checks: tuple[Check, ...]
    project: bool = False
    theory_in_force: bool = False

    @property
    def projects_to_shown(self) -> bool:
        """The shape-collapse coordinate: ``--project`` erases information only under a theory."""
        return self.project and self.theory_in_force

    def __post_init__(self) -> None:
        provided = populates(self.mode, self.projects_to_shown)
        for check in self.checks:
            missing = check.reads - provided
            if missing:
                want = ", ".join(sorted(field.value for field in missing))
                have = ", ".join(sorted(field.value for field in provided))
                raise RoutingError(
                    f"{check.label} reads {{{want}}}, which {self.mode.name} "
                    f"(projects_to_shown={self.projects_to_shown}) populates only {{{have}}} — the "
                    "reads ⊆ populates wiring rule is violated (an elenctic bug, not a verdict)"
                )


def reads_full_census(check: Check) -> bool:
    """Whether ``check`` reads a projection-sensitive full-census token (the multiplicity/assignment
    view). A pure vocabulary-membership test over ``check.reads`` — no stored bool to drift, so a
    future check that reads a full token is automatically an assignment/multiplicity observer."""
    return bool(check.reads & {Field.FULL_CENSUS, Field.FULL_OPTIMAL_CENSUS})


def should_project(theory_in_force: bool, mode: Mode, checks: tuple[Check, ...]) -> bool:
    """Whether a run may project its census onto shown atoms — the contract-induced projection rule.
    Pure; carried on the :class:`Run`. A non-enumeration mode has nothing to collapse. With no
    theory in force the assignment is empty, so projection is information-preserving and always
    safe. Under a theory, project iff no rider observes the full (multiplicity/assignment) census.

    Soundness is enforced, not assumed: a mis-derive (projecting with a full-view reader present)
    builds the ``Run`` against the projected ``populates``, the full token is absent, and
    ``Run.__post_init__`` raises ``RoutingError`` before any solve, so ``should_project`` reduces to
    the ``reads ⊆ populates`` feasibility check. No ``bool(checks)`` guard: a check-less enumeration
    has no verdict to preserve, so the facade default (``solve(project=False)``) handles raw callers
    separately from this soundness predicate."""
    if mode not in {Mode.ENUM_ALL, Mode.OPTIMAL_ENUM}:
        return False
    if not theory_in_force:
        return True
    return not any(reads_full_census(check) for check in checks)


def runs_for(exp: Expectation, theory_in_force: bool = False) -> tuple[Run, ...]:
    """Derive the coalesced runs an expectation requires (pure). ``theory_in_force`` (whether the
    case's solver is a theory solver) parameterizes the per-run projection decision; it defaults
    ``False`` (pure clingo) so the solver-less dry-run and existing callers are unaffected."""
    match exp:
        case Unsat():
            return (Run(Mode.DEFAULT, (checks.expect_unsat(),), theory_in_force=theory_in_force),)
        case Sat():
            return _sat_runs(exp, theory_in_force)
        case _:
            assert_never(exp)


def _sat_runs(exp: Sat, theory_in_force: bool) -> tuple[Run, ...]:
    """Coalesce a satisfiable contract's tags onto the run-configuration taxonomy.

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
        add(Mode.OPTIMAL_ENUM, checks.has_optimal_model(exp.optimal_model))
    if exp.cautious_optimal:
        add(Mode.OPTIMAL_ENUM, checks.cautious_optimal_contains(exp.cautious_optimal))
    if exp.brave_optimal:
        add(Mode.OPTIMAL_ENUM, checks.brave_optimal_contains(exp.brave_optimal))
    if exp.count_optimal is not None:
        add(Mode.OPTIMAL_ENUM, checks.count_optimal_is(exp.count_optimal))
    if exp.assign_optimal:
        add(Mode.OPTIMAL_ENUM, checks.assign_optimal_contains(exp.assign_optimal))
    if exp.cost is not None:
        # @cost rides the shared Opt(P) enumeration when an optimal-base mode is present, else a
        # cheap single-optimum solve. Optimal-base membership lives on Sat (one home).
        add(Mode.OPTIMAL_ENUM if exp.has_optimal_base else Mode.OPTIMAL, checks.cost_is(exp.cost))

    for query in exp.queries:
        add(_query_mode(query), checks.query_matches(query))

    # @expect sat reads ∅ (the arm is the answer), so it could ride any run; it rides an existing
    # full enumeration when one exists, else a cheap DEFAULT 1-model solve — deliberately not an
    # expensive cautious/brave/opt run, which is likelier to time out and report UNDECIDED where the
    # cheap solve would decide satisfiability. (A more refined UNDECIDED treatment is deferred.)
    add(Mode.ENUM_ALL if Mode.ENUM_ALL in bucket else Mode.DEFAULT, checks.expect_sat())

    return tuple(
        Run(
            mode,
            tuple(carried),
            project=should_project(theory_in_force, mode, tuple(carried)),
            theory_in_force=theory_in_force,
        )
        for mode, carried in bucket.items()
    )


def _query_mode(query: Query) -> Mode:
    """The run a ``@query`` rides (corrected Def 2.2.2), keyed on the shared ``query.classify`` so
    route and read never disagree. A *singleton* ground query and a yes/no binding read ⋂
    (``CAUTIOUS_ALL``); a *conjunctive* ground query needs the census (its "no" is ``∀M ∃i: l̄i∈M``,
    not a ⋂ property), and an ``unknown`` binding needs ⋃ too, so both ride a full enumeration
    (``ENUM_ALL``, which carries both ⋂ and ⋃)."""
    form = classify(query)
    match form:
        case QueryForm.SINGLETON_GROUND | QueryForm.BINDING_SETTLED:
            return Mode.CAUTIOUS_ALL
        case QueryForm.CONJUNCTIVE_GROUND | QueryForm.BINDING_UNKNOWN:
            return Mode.ENUM_ALL
        case _:
            assert_never(form)


def _main() -> None:
    """Inspect the run plan (the dry-run): parse a ``.lp`` file and print the runs it derives — each
    ``Mode`` with its checks, the ``reads``/``populates`` routing made legible before any solve."""
    import sys
    from pathlib import Path

    from elenctic.expectation import parse

    if len(sys.argv) != 2:
        print("usage: python -m elenctic.run <file.lp>", file=sys.stderr)
        raise SystemExit(2)
    path = Path(sys.argv[1])
    for run in runs_for(parse(path.read_text(encoding="utf-8"), source=str(path))):
        # solver-independent: the dry-run shows the mode and each check's reads, not the projection
        # decision (which needs the solver — narrated by the CLI's --explain, which has the case).
        print(f"{run.mode.name}:")
        for check in run.checks:
            name = f"{check.label} ({check.subject})" if check.subject else check.label
            reads = ", ".join(sorted(field.value for field in check.reads)) or "—"
            print(f"    {name} — reads {{{reads}}}")


if __name__ == "__main__":
    _main()
