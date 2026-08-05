"""Case discovery — the content-keyed corpus walk.

``discover(target)`` runs a single ``.lp`` file or walks a directory, collecting every
file that carries a contract. The **collection predicate**: a ``.lp`` file is a *case* iff it
contains a known elenctic tag (:func:`~elenctic.expectation.has_contract`), else a *library* — an
``#include`` target, never run directly. The solver is **declared** (``@elenctic solver``, default
``clingo``), never read from a filename. The program under test is the case file plus its resolved
``#include``s; the loader/inspector resolve them, so a :class:`Case` carries just its own path.

Discovery enforces the preconditions and the theory-presence gate over the
**resolved program** (:func:`check_program` over :func:`elenctic.program.inspect`), not the
case-file text — so an encoding moved into an ``#include``d library is still gated correctly. It is
loud, never silent: a precondition violation is a :class:`DiscoveryError`, a malformed contract the
sourced :class:`~elenctic.expectation.ContractError`, a bad ``#include`` / non-UTF-8 program the
:class:`~elenctic.program.ProgramError` — each with provenance, never a raw clingo trace. Pure over
the tree (filesystem reads its only effect); only ``solvers.py`` touches a solver.

The collection scan reads tolerantly (``errors="replace"``): the contract tags are ASCII, so a
non-UTF-8 *library* is simply skipped, while a non-UTF-8 *case* is collected and then rejected with
a friendly, ``source:line``-carrying diagnostic — a ``ContractError`` if the bad byte falls in a
parsed ``@``-payload, otherwise a ``ProgramError`` at the resolved-program inspection.

The shown vocabulary is keyed by sign-aware predicate **signature** ``(name, arity)`` (from
``program.inspect``), so a ``@query`` contrary ``#show``n at the wrong arity (an authoring typo) is
a *loud* precondition failure, not a silent wrong PASS — the former name-only boundary is closed.
"""

from dataclasses import dataclass
from importlib.util import find_spec
from pathlib import Path

from clingo import Symbol

from elenctic.expectation import ContractError, Expectation, Sat, has_contract, parse_contract
from elenctic.program import ProgramError, ProgramFacts, inspect
from elenctic.query import Answer, BindingQuery, GroundQuery, Query, QueryLiteral
from elenctic.registry import BACKING_MODULES, Solver, provides_theory
from elenctic.terms import contrary

__all__ = [
    "Case",
    "Corpus",
    "DiscoveryError",
    "HygieneReport",
    "SolverUnavailableError",
    "check_program",
    "check_solver_available",
    "discover",
    "inspect_corpus",
]


class DiscoveryError(Exception):
    """A corpus that violates a discovery-time precondition or an
    explicitly-named contract-free file. Loud by design — discovery never silently drops a
    case nor silently mis-classifies one."""


class SolverUnavailableError(DiscoveryError, ImportError):
    """A case's declared solver is not installed in this environment.

    Deliberately both: a ``DiscoveryError``, because a corpus naming a solver this environment
    lacks is a corpus that cannot be run, and an ``ImportError``, because a missing optional
    dependency is exactly what this is and is what a caller reaching for one expects to catch.
    Either idiom works, so neither a reader following elenctic's error families nor one following
    Python's convention is caught out.

    Raised from the per-case check and from the solver facade alike, so one condition has one type
    wherever a caller meets it."""


@dataclass(frozen=True, slots=True)
class Case:
    """One case: a contract-bearing ``.lp`` file, its declared solver, parsed contract, and shown
    vocabulary. The program under test is this file plus its resolved ``#include``s — the loader
    resolves them, so ``files`` is just this path. ``shown`` is the shown predicate **signatures**
    ``(sign-aware-name, arity)`` (e.g. ``{("reachable", 1), ("-reachable", 1)}``) read from the
    resolved program. Provenance-rich: the parsed ``expectation`` keeps its ``notes``, and
    ``contract_source`` names the case file, so a renderer or docs tool reads it without re-parsing.
    """

    path: Path
    solver: Solver
    expectation: Expectation
    shown: frozenset[tuple[str, int]]

    @property
    def contract_source(self) -> Path:
        """The file the contract was parsed from — the case file itself."""
        return self.path

    @property
    def files(self) -> tuple[Path, ...]:
        """The program the facade loads: the case file (its ``#include``s resolve at load time)."""
        return (self.path,)


# What each hygiene observation says about the file it concerns. One home per observation, because
# a run states them twice — once in the end-of-run summary a reader sees, once in the record a
# consumer reads — and two copies of a sentence drift the first time either is edited.
ORPHAN_LIBRARY = (
    "carries no contract and no case #includes it (a forgotten case, or a dead library?)"
)
UNDECLARED_SOLVER = "defaulted to clingo (declare @elenctic solver for reproducibility)"


@dataclass(frozen=True, slots=True, kw_only=True)
class HygieneReport:
    """Corpus hygiene — the third strictness axis, distinct from the always-error closed
    vocabulary and soundness floor. These are observations, never verdicts, and the two have
    different default footing (the idiomatic asymmetry), which is why a run reports one of them
    unasked and stays quiet about the other.

    What this shape carries is the observation and nothing about how loudly to take it. How loudly
    is a policy of the invocation rather than a property of what was seen, so it is decided once,
    where a run records the observation, and every reading of it comes off that one decision — what
    is printed, and what fails the run. Restating the footing here would be a second copy of it, and
    the copy that is not consulted is the one that goes stale.

    ``orphan_libraries`` — contract-free ``.lp`` files in the walked tree that no case loads (the
    backstop: a forgotten case, or a dead library). ``undeclared_solvers`` — case files that did not
    declare ``@elenctic solver`` and so defaulted to ``clingo``. Both are absolute-or-walk-relative
    paths, in deterministic (sorted-walk) order.

    Built by keyword, like every other record a consumer meets. The two fields are adjacent and have
    the same type, which is the exact hazard the rule exists for: transposed, they type-check clean
    and read as a plausible report, and every orphan library would then be reported as a case that
    did not declare its solver.
    """

    orphan_libraries: tuple[Path, ...]
    undeclared_solvers: tuple[Path, ...]

    @property
    def clean(self) -> bool:
        """Whether the corpus carries no hygiene observations at all (no orphans, no undeclared
        solvers) — the raw detection state, independent of what any invocation makes of it."""
        return not (self.orphan_libraries or self.undeclared_solvers)


@dataclass(frozen=True, slots=True)
class Corpus:
    """The result of hygiene-aware discovery (:func:`inspect_corpus`): the cases to run and
    the corpus :class:`HygieneReport`. This is what a run starts from; what it produced is the
    runner's :class:`~elenctic.outcome.RunOutcome`, which is the shape a report is built from."""

    cases: tuple[Case, ...]
    hygiene: HygieneReport
    unrunnable: tuple[tuple[Path, Exception], ...] = ()


@dataclass(frozen=True, slots=True)
class _Walk:
    """The one-pass walk result shared by :func:`discover` (cases only) and :func:`inspect_corpus`
    (cases + hygiene). ``used`` is the union of every case's resolved ``sources`` (the case file
    plus its transitive ``#include``s, from clingo's own parse) — the orphan check's authoritative
    "is this library actually loaded?" set, so the backstop never re-derives include resolution."""

    cases: tuple[Case, ...]
    undeclared: tuple[Path, ...]
    libraries: tuple[Path, ...]
    used: frozenset[Path]
    unrunnable: tuple[tuple[Path, Exception], ...]


def discover(target: Path) -> tuple[Case, ...]:
    """Discover cases under ``target``. A single file is one case; a
    directory is walked (sorted, deterministic) for contract-bearing ``.lp`` files. An explicitly
    named contract-free file is loud (never a silent no-op); a contract-free file in a walked
    directory is a library (skipped). Raises :class:`DiscoveryError` on a precondition violation,
    :class:`~elenctic.expectation.ContractError` on a malformed contract, or
    :class:`~elenctic.program.ProgramError` on a bad ``#include`` or non-UTF-8 program.
    For the cases *and* corpus hygiene (the ``--strict`` dial), use :func:`inspect_corpus`.

    A walked file that cannot be turned into a case raises here, because this signature has nowhere
    to report it and a silently smaller tuple would be a wrong answer. :func:`inspect_corpus`
    carries those files instead, which is what lets the CLI run the rest of the corpus.
    """
    walk = _classify(target)
    for _path, exc in walk.unrunnable:
        raise exc
    return walk.cases


def inspect_corpus(target: Path) -> Corpus:
    """Discover cases under ``target`` **and** report corpus hygiene — the CLI's
    hygiene-aware entry. One walk yields the cases and a :class:`HygieneReport`: orphan libraries
    (a contract-free ``.lp`` no case loads — the backstop) and undeclared-solver cases (defaulted
    to ``clingo``). A library is an orphan iff its resolved path is absent from ``used`` — the files
    clingo actually loads across all cases (:attr:`elenctic.program.ProgramFacts.sources`), so the
    check matches clingo's include resolution exactly rather than re-scanning text. What is reported
    is the observation; how loudly a given invocation takes it is graded where the run records it,
    and it is never a verdict. Raises the same loud errors as :func:`discover` on a mis-shaped
    corpus.
    """
    walk = _classify(target)
    orphans = tuple(library for library in walk.libraries if library.resolve() not in walk.used)
    return Corpus(
        walk.cases,
        HygieneReport(orphan_libraries=orphans, undeclared_solvers=walk.undeclared),
        walk.unrunnable,
    )


def _classify(target: Path) -> _Walk:
    """Walk ``target`` once — the single traversal shared by :func:`discover` (cases only) and
    :func:`inspect_corpus` (cases + hygiene). Returns a :class:`_Walk`: the cases, the
    undeclared-solver case paths, the contract-free library paths (orphan candidates), and ``used``
    (the union of every case's resolved ``sources``). Loud on a missing target or an
    explicitly-named contract-free file; a contract-free file under a walked directory is
    a library, collected separately, never run.
    """
    if not target.exists():
        raise DiscoveryError(
            f"{target}: no such file or directory — a named target that does not exist tests "
            "nothing; a silent pass would hide a typo or a moved file (loud over silent)"
        )
    if target.is_file():
        text = _read(target)
        if not has_contract(text):
            raise DiscoveryError(
                f"{target}: not a case — it carries no elenctic contract tag. A "
                "contract-free .lp is a library (an #include target), not a runnable case."
            )
        # A named file gives no directory to take as the corpus, so its own is the boundary: a
        # sibling library is reachable, the tree above it is not.
        case, declared, sources = _make_case(target, text, target.parent.resolve())
        defaulted: tuple[Path, ...] = () if declared else (target,)
        # An explicitly named file is not walked, so it keeps the loud contract: the one thing the
        # user asked about must not be reported as a corpus that happened to contain nothing.
        return _Walk((case,), defaulted, (), sources, ())
    root = target.resolve()  # the containment boundary every case's sources must stay under
    cases: list[Case] = []
    undeclared: list[Path] = []
    libraries: list[Path] = []
    used: set[Path] = set()
    unrunnable: list[tuple[Path, Exception]] = []
    for path in sorted(target.rglob("*.lp")):
        # Whether a file can be run is a fact about that file. A walked file that cannot be read,
        # parsed, or resolved is recorded against itself and the walk continues, so one unusable
        # file costs its own result and no other's — the same guarantee the runner gives a case
        # that will not ground, at the stage before it.
        try:
            text = _read(path)
            if not has_contract(text):
                libraries.append(path)
                continue
            case, declared, sources = _make_case(path, text, root)
        except (ContractError, DiscoveryError, ProgramError) as exc:
            unrunnable.append((path, exc))
            continue
        cases.append(case)
        used |= sources
        if not declared:
            undeclared.append(path)
    return _Walk(
        tuple(cases), tuple(undeclared), tuple(libraries), frozenset(used), tuple(unrunnable)
    )


def _read(path: Path) -> str:
    """Read a ``.lp`` file for the contract scan, tolerant of encoding (``errors="replace"``): the
    contract tags are ASCII, so a non-UTF-8 library is skipped and a non-UTF-8 case is rejected
    (friendly, with ``source:line``) at whichever stage first decodes the bad byte — ``parse`` for a
    contract ``@``-payload, else the resolved-program inspection. An unreadable entry — a directory
    or a broken symlink named ``*.lp`` (both matched by ``rglob``), or a permission-denied file — is
    a friendly ``DiscoveryError`` with provenance, never a raw trace."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DiscoveryError(f"{path}: cannot read this .lp entry — {exc}") from exc


def _within_root(sources: frozenset[Path], root: Path, path: Path) -> None:
    """Refuse a case that loads a file from outside ``root`` — the corpus containment rule.

    ``#include`` resolution belongs to clingo, which opens whatever path it is handed, so a corpus
    can otherwise name any file the process can read. That matters because a corpus is untrusted
    input: it is cloned, or it arrives in a pull request. What is read does not stay read, either —
    a contract that fails renders the model it was judged against, so an unconstrained include is a
    way to publish another file's content through elenctic's own diagnostics.

    The boundary is the root the run was pointed at, not the case's own directory: reaching upward
    and across to a shared encoding is the ordinary shape of a corpus, and a rule that cost that
    would buy nothing anyone would keep. ``sources`` is already resolved, so a symlink is judged by
    where it lands rather than where it sits. The diagnostic names the escaping path and nothing
    from inside it, since disclosure is the thing being prevented."""
    escaped = sorted(str(source) for source in sources if not source.is_relative_to(root))
    if escaped:
        raise DiscoveryError(
            f"{path}: this case loads {', '.join(escaped)}, which is outside the corpus at {root}. "
            "A case may only include files from the corpus it belongs to — a corpus is run as "
            "given, so an include reaching past it would read a file the run was never pointed at."
        )


def _make_case(path: Path, text: str, root: Path) -> tuple[Case, bool, frozenset[Path]]:
    """Build one case from a contract-bearing file: parse the contract (behavioral + declared
    solver, default ``clingo``), inspect the resolved program, enforce the preconditions. Returns
    the case, whether its solver was *declared* (vs defaulted to clingo), and the resolved source
    files it spans (``facts.sources``) — the two hygiene facts, kept off :class:`Case`
    (corpus-hygiene concerns, not solving ones)."""
    contract = parse_contract(text, source=str(path))
    declared = contract.solver is not None
    solver: Solver = contract.solver or "clingo"  # the stated default
    facts = inspect((path,))
    _within_root(facts.sources, root, path)
    check_program(contract.expectation, facts, solver, path)
    return Case(path, solver, contract.expectation, facts.shown), declared, facts.sources


def _installed(module: str) -> bool:
    """Whether ``module`` can be imported, determined without importing it. ``find_spec`` raises
    rather than returning ``None`` for some broken installations, which counts as absent here."""
    try:
        return find_spec(module) is not None
    except ImportError, ValueError:
        return False


def check_solver_available(solver: Solver, where: Path) -> None:
    """Check the declared ``solver`` is installed, before a run reaches its facade. Loud
    (``DiscoveryError``), never a verdict: a case whose solver is absent cannot be run at all, so
    there is no answer to report about it, and an import failure raised from inside a solver facade
    names none of what the reader needs.

    Checked **per case, at run time** rather than during the corpus walk. An absent optional backend
    then costs only the cases that declare it — the rest of the corpus still runs and still reports,
    instead of one missing package zeroing the whole run — and a dry run, which never reaches a
    solver, does not require one to be installed."""
    module = BACKING_MODULES[solver]
    if _installed(module):
        return
    # Only the theory branch is reachable today, and saying so is better than a fallback that
    # cannot be exercised: the sole non-theory solver is clingo, and this module imports from clingo
    # at load, so a process that got here has it. The branch stays because the registry is meant to
    # grow, and a second optional backend makes it live the day it is added.
    remedy = (
        'install the theory extra: pip install "elenctic[theory]"'
        if provides_theory(solver)
        else f"add {module} to your environment"
    )
    raise SolverUnavailableError(
        f"{where}: this case declares @elenctic solver {solver}, but {module} is not installed "
        f"— {remedy}"
    )


def check_program(
    expectation: Expectation, facts: ProgramFacts, solver: Solver, where: Path
) -> None:
    """Enforce the discovery-time preconditions + the theory-presence gate over the **resolved
    program** (``facts``), under the **declared** ``solver``. Loud (``DiscoveryError``), never a
    verdict. The gates: a theory atom under a non-theory solver (presence, never identity); a
    theory-bearing contract under a non-theory solver; the optimization gate, the
    ``@cost``-over-``#maximize`` guard, and the shown contrary. The program-side and contract-side
    theory gates are complementary duals; both are required."""
    if facts.has_theory_atom and not provides_theory(solver):
        raise DiscoveryError(
            f"{where}: the resolved program has a theory atom (&…), but the solver is {solver}, "
            "which does not interpret it — clingo grounds theory atoms and silently ignores the "
            "constraints (a wrong PASS). Declare @elenctic solver clingcon"
        )
    if not isinstance(expectation, Sat):
        return
    if expectation.requires_theory and not provides_theory(solver):
        raise DiscoveryError(
            f"{where}: a theory binding (@assign, @assign optimal, or a where-witness) reads the "
            f"theory half of the observable, so it needs a theory solver (clingcon), not {solver}"
        )
    if expectation.requires_optimization and not facts.has_optimization:
        raise DiscoveryError(
            f"{where}: @cost/@optimal/an optimal-base tag needs an optimizing encoding "
            "(#minimize/#maximize/:~), but the resolved program has none"
        )
    if expectation.reads_all_answer_sets and facts.has_theory_optimization:
        raise DiscoveryError(
            f"{where}: @model/@count/@assign/@cautious/@brave/@query read AS(P), the whole "
            "answer-set collection, which elenctic cannot compute over a theory-native objective "
            "(&minimize/&maximize): the theory's propagator drives the search to the optimum, and "
            "no clingo setting switches that off, so the enumeration would silently cover only "
            "part of AS(P). Move the objective into ASP (#minimize/#maximize/:~), which the AS(P) "
            "modes do switch off, or drop to @expect sat / an optimal-base tag"
        )
    if expectation.cost is not None and facts.has_maximize:
        raise DiscoveryError(
            f"{where}: @cost over a #maximize objective is not supported — clingo reports a "
            "maximize cost in negated form, and natural-value normalisation is deferred. Use "
            "#minimize, or an optimal-base tag (@optimal/@cautious optimal/@count optimal)"
        )
    for query in expectation.queries:
        if missing := _contraries_needed(query.value) - facts.shown:
            needed = ", ".join(f"{name}/{arity}" for name, arity in sorted(missing))
            have = ", ".join(f"{name}/{arity}" for name, arity in sorted(facts.shown))
            raise DiscoveryError(
                f"{where}: a no/unknown @query reads the contrary literal(s) {needed} off the "
                f"shown ⋂/⋃, but they are absent from the shown vocabulary {{{have}}}"
            )


def _contraries_needed(query: Query) -> frozenset[tuple[str, int]]:
    """The shown predicate *signatures* ``(sign-aware-name, arity)`` a query reads as *contraries*
    off ⋂/⋃, which must therefore be shown:

    - a ground ``no``/``unknown`` query needs **every** conjunct's contrary. Under the corrected ∀∃
      "no" (each model may falsify a *different* conjunct), any conjunct's contrary may be the
      witness, so requiring all of them is the conservative *sound* reading (it can over-require,
      but never silently passes an unsound case);
    - a binding query needs the goal's contrary when ``unknown`` (its unknown-set reads ``-q`` off
      ⋃/⋂, so an unshown ``-q`` would under-compute it), or ``no`` with a **non-empty** set (an
      empty ``no`` set is vacuously satisfiable without ``-q``: the "non-empty" carve-out).

    A ``yes`` query reads only the positive literal, covered by no rule this version
    precondition, not this rule. Keyed by full ``(name, arity)`` signature, so a contrary
    ``#show``n at the wrong arity is caught loud rather than silently unobservable."""
    match query:
        case GroundQuery(answer, conjuncts) if answer in {Answer.no, Answer.unknown}:
            return frozenset(_signed_signature(contrary(conjunct)) for conjunct in conjuncts)
        case BindingQuery(Answer.unknown, goal, _):
            return frozenset({_goal_contrary_signature(goal)})
        case BindingQuery(Answer.no, goal, bindings) if bindings:
            return frozenset({_goal_contrary_signature(goal)})
        case _:
            return frozenset()


def _signed_signature(literal: Symbol) -> tuple[str, int]:
    """The ``(sign-aware-name, arity)`` signature of a ground literal, matching ``#show``
    vocabulary."""
    name = literal.name if literal.positive else f"-{literal.name}"
    return (name, len(literal.arguments))


def _goal_contrary_signature(goal: QueryLiteral) -> tuple[str, int]:
    """The ``(sign-aware-name, arity)`` of a binding goal's *contrary* literal:
    ``-q`` for ``q``, ``q`` for ``-q`` — the dual of :func:`_signed_signature` for a (non-ground)
    goal, carrying the goal's arity."""
    name = f"-{goal.name}" if goal.positive else goal.name
    return (name, goal.arity)


def _main() -> None:
    """Inspect discovery: walk a target (a file or a directory) and list the discovered cases."""
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m elenctic.discovery <file.lp | directory>", file=sys.stderr)
        raise SystemExit(2)
    for case in discover(Path(sys.argv[1])):
        print(f"{case.contract_source} [{case.solver}]")


if __name__ == "__main__":
    _main()
