"""Case discovery — the content-keyed corpus walk (spec §1, §2, §5).

``discover(target)`` runs a single ``.lp`` file (issue #3) or walks a directory, collecting every
file that carries a contract. The **collection predicate** (R3): a ``.lp`` file is a *case* iff it
contains a known elenctic tag (:func:`~elenctic.expectation.has_contract`), else a *library* — an
``#include`` target, never run directly. The solver is **declared** (``@elenctic solver``, default
``clingo``), never read from a filename. The program under test is the case file plus its resolved
``#include``s; the loader/inspector resolve them, so a :class:`Case` carries just its own path.

Discovery enforces the §2.2-rule-4 preconditions and the R1 theory-presence gate over the
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
from pathlib import Path

from clingo import Symbol

from elenctic.expectation import Expectation, Sat, has_contract, parse_contract
from elenctic.program import ProgramFacts, inspect
from elenctic.query import Answer, BindingQuery, GroundQuery, Query, QueryLiteral
from elenctic.registry import Solver, provides_theory
from elenctic.terms import contrary

__all__ = [
    "Case",
    "Corpus",
    "DiscoveryError",
    "HygieneReport",
    "check_program",
    "discover",
    "inspect_corpus",
]


class DiscoveryError(Exception):
    """A corpus that violates a discovery-time precondition (§2.2 rule 4 / the R1 theory gate) or an
    explicitly-named contract-free file (spec §1). Loud by design — discovery never silently drops a
    case nor silently mis-classifies one."""


@dataclass(frozen=True, slots=True)
class Case:
    """One case: a contract-bearing ``.lp`` file, its declared solver, parsed contract, and shown
    vocabulary. The program under test is this file plus its resolved ``#include``s — the loader
    resolves them, so ``files`` is just this path. ``shown`` is the shown predicate **signatures**
    ``(sign-aware-name, arity)`` (e.g. ``{("reachable", 1), ("-reachable", 1)}``) read from the
    resolved program. Provenance-rich (dx#2): the parsed ``expectation`` keeps its ``notes``, and
    ``contract_source`` names the case file, so a renderer or docs tool reads it without re-parsing.
    """

    path: Path
    solver: Solver
    expectation: Expectation
    shown: frozenset[tuple[str, int]]

    @property
    def contract_source(self) -> Path:
        """The file the contract was parsed from (dx#2 provenance) — the case file itself."""
        return self.path

    @property
    def files(self) -> tuple[Path, ...]:
        """The program the facade loads: the case file (its ``#include``s resolve at load time)."""
        return (self.path,)


@dataclass(frozen=True, slots=True)
class HygieneReport:
    """Corpus hygiene — the third strictness axis (spec §5), distinct from the always-error closed
    vocabulary and soundness floor. These are observations, never verdicts, and the two records have
    different default footing (the idiomatic asymmetry): an **orphan library** is a real corpus
    smell — *warned* by default, an *error* under ``--strict`` (the CI gate). An **undeclared
    solver** is a mere explicitness nudge — relying on the stated ``clingo`` default is legitimate,
    so it is *silent* by default and an *error* only under ``--strict`` (the ``mypy --strict`` /
    ``pytest --strict-markers`` posture: a default is fine until you opt into explicitness, and the
    Unix rule of silence says do not nag about the expected case). :func:`render` applies this.

    ``orphan_libraries`` — contract-free ``.lp`` files in the walked tree that no case loads (the §1
    backstop: a forgotten case, or a dead library). ``undeclared_solvers`` — case files that did not
    declare ``@elenctic solver`` and so defaulted to ``clingo``. Both are absolute-or-walk-relative
    paths, in deterministic (sorted-walk) order.
    """

    orphan_libraries: tuple[Path, ...]
    undeclared_solvers: tuple[Path, ...]

    @property
    def clean(self) -> bool:
        """Whether the corpus carries no hygiene observations at all (no orphans, no undeclared
        solvers) — the raw detection state, independent of the mode-aware :func:`render`."""
        return not (self.orphan_libraries or self.undeclared_solvers)

    def render(self, *, strict: bool) -> tuple[str, ...]:
        """The hygiene lines to report in this mode (empty when there is nothing to show). Orphan
        libraries are always reported (warned by default, error under ``--strict``); undeclared
        solvers only under ``--strict`` (silent by default — the stated ``clingo`` default is
        legitimate). Aggregated and reported together (spec §5)."""
        lines = [
            f"orphan library: {path} carries no contract and no case #includes it "
            "(a forgotten case, or a dead library?)"
            for path in self.orphan_libraries
        ]
        if strict and self.undeclared_solvers:
            listed = ", ".join(str(path) for path in self.undeclared_solvers)
            lines.append(
                f"undeclared solver: {len(self.undeclared_solvers)} case(s) defaulted to clingo "
                f"(declare @elenctic solver for reproducibility): {listed}"
            )
        return tuple(lines)


@dataclass(frozen=True, slots=True)
class Corpus:
    """The result of hygiene-aware discovery (:func:`inspect_corpus`, spec §5): the cases to run and
    the corpus :class:`HygieneReport`. The CLI runs ``cases`` and reports ``hygiene`` (warn-by-
    default / error-under-``--strict``); issue #2 (``--json``) will serialize the same pair."""

    cases: tuple[Case, ...]
    hygiene: HygieneReport


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


def discover(target: Path) -> tuple[Case, ...]:
    """Discover cases under ``target`` (spec §1, §2). A single file is one case (issue #3); a
    directory is walked (sorted, deterministic) for contract-bearing ``.lp`` files. An explicitly
    named contract-free file is loud (never a silent no-op); a contract-free file in a walked
    directory is a library (skipped). Raises :class:`DiscoveryError` on a precondition violation,
    :class:`~elenctic.expectation.ContractError` on a malformed contract, or
    :class:`~elenctic.program.ProgramError` on a bad ``#include`` or non-UTF-8 program.
    For the cases *and* corpus hygiene (the ``--strict`` dial), use :func:`inspect_corpus`.
    """
    return _classify(target).cases


def inspect_corpus(target: Path) -> Corpus:
    """Discover cases under ``target`` **and** report corpus hygiene (spec §5) — the CLI's
    hygiene-aware entry. One walk yields the cases and a :class:`HygieneReport`: orphan libraries
    (a contract-free ``.lp`` no case loads — the §1 backstop) and undeclared-solver cases (defaulted
    to ``clingo``). A library is an orphan iff its resolved path is absent from ``used`` — the files
    clingo actually loads across all cases (:attr:`elenctic.program.ProgramFacts.sources`), so the
    check matches clingo's include resolution exactly rather than re-scanning text. Hygiene is
    warn-by-default / error-under-``--strict`` at the CLI, never a verdict. Raises the same loud
    errors as :func:`discover` on a mis-shaped corpus.
    """
    walk = _classify(target)
    orphans = tuple(library for library in walk.libraries if library.resolve() not in walk.used)
    return Corpus(
        walk.cases, HygieneReport(orphan_libraries=orphans, undeclared_solvers=walk.undeclared)
    )


def _classify(target: Path) -> _Walk:
    """Walk ``target`` once — the single traversal shared by :func:`discover` (cases only) and
    :func:`inspect_corpus` (cases + hygiene). Returns a :class:`_Walk`: the cases, the
    undeclared-solver case paths, the contract-free library paths (orphan candidates), and ``used``
    (the union of every case's resolved ``sources``). Loud on a missing target or an
    explicitly-named contract-free file (spec §1); a contract-free file under a walked directory is
    a library, collected separately, never run.
    """
    if not target.exists():
        raise DiscoveryError(
            f"{target}: no such file or directory — a named target that does not exist tests "
            "nothing; a silent pass would hide a typo or a moved file (loud over silent, §1)"
        )
    if target.is_file():
        text = _read(target)
        if not has_contract(text):
            raise DiscoveryError(
                f"{target}: not a case — it carries no elenctic contract tag (spec §1). A "
                "contract-free .lp is a library (an #include target), not a runnable case."
            )
        case, declared, sources = _make_case(target, text)
        defaulted: tuple[Path, ...] = () if declared else (target,)
        return _Walk((case,), defaulted, (), sources)
    cases: list[Case] = []
    undeclared: list[Path] = []
    libraries: list[Path] = []
    used: set[Path] = set()
    for path in sorted(target.rglob("*.lp")):
        text = _read(path)
        if not has_contract(text):
            libraries.append(path)
            continue
        case, declared, sources = _make_case(path, text)
        cases.append(case)
        used |= sources
        if not declared:
            undeclared.append(path)
    return _Walk(tuple(cases), tuple(undeclared), tuple(libraries), frozenset(used))


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


def _make_case(path: Path, text: str) -> tuple[Case, bool, frozenset[Path]]:
    """Build one case from a contract-bearing file: parse the contract (behavioral + declared
    solver, default ``clingo``), inspect the resolved program, enforce the preconditions. Returns
    the case, whether its solver was *declared* (vs defaulted to clingo), and the resolved source
    files it spans (``facts.sources``) — the two hygiene facts (§5), kept off :class:`Case`
    (corpus-hygiene concerns, not solving ones)."""
    contract = parse_contract(text, source=str(path))
    declared = contract.solver is not None
    solver: Solver = contract.solver or "clingo"  # the stated default (R1)
    facts = inspect((path,))
    check_program(contract.expectation, facts, solver, path)
    return Case(path, solver, contract.expectation, facts.shown), declared, facts.sources


def check_program(
    expectation: Expectation, facts: ProgramFacts, solver: Solver, where: Path
) -> None:
    """Enforce the §2.2-rule-4 preconditions + the R1 theory-presence gate over the **resolved
    program** (``facts``), under the **declared** ``solver``. Loud (``DiscoveryError``), never a
    verdict. R1: a theory atom under a non-theory solver (presence, never identity). R4: a
    theory-bearing contract under a non-theory solver. R2: the optimization gate, the
    ``@cost``-over-``#maximize`` guard, the shown contrary. R1 (program-side) and R4 (contract-side)
    are complementary duals; both are required."""
    if facts.has_theory_atom and not provides_theory(solver):
        raise DiscoveryError(
            f"{where}: the resolved program has a theory atom (&…), but the solver is {solver}, "
            "which does not interpret it — clingo grounds theory atoms and silently ignores the "
            "constraints (a wrong PASS). Declare @elenctic solver clingcon (spec §4, R1)"
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
            "(#minimize/#maximize/:~), but the resolved program has none (spec §2.2 rule 4)"
        )
    if expectation.cost is not None and facts.has_maximize:
        raise DiscoveryError(
            f"{where}: @cost over a #maximize objective is not supported in v1 — clingo reports a "
            "maximize cost in negated form, and natural-value normalisation is deferred. Use "
            "#minimize, or an optimal-base tag (@optimal/@cautious optimal/@count optimal)"
        )
    for query in expectation.queries:
        if missing := _contraries_needed(query) - facts.shown:
            needed = ", ".join(f"{name}/{arity}" for name, arity in sorted(missing))
            have = ", ".join(f"{name}/{arity}" for name, arity in sorted(facts.shown))
            raise DiscoveryError(
                f"{where}: a no/unknown @query reads the contrary literal(s) {needed} off the "
                f"shown ⋂/⋃, but they are absent from the shown vocabulary {{{have}}} "
                "(spec §2.0/§2.2 rule 4)"
            )


def _contraries_needed(query: Query) -> frozenset[tuple[str, int]]:
    """The shown predicate *signatures* ``(sign-aware-name, arity)`` a query reads as *contraries*
    off ⋂/⋃, which must therefore be shown (§2.2 rule 4):

    - a ground ``no``/``unknown`` query needs **every** conjunct's contrary. Under the corrected ∀∃
      "no" (each model may falsify a *different* conjunct, §2.1), any conjunct's contrary may be the
      witness, so requiring all of them is the conservative *sound* reading (it can over-require,
      but never silently passes an unsound case);
    - a binding query needs the goal's contrary when ``unknown`` (its unknown-set reads ``-q`` off
      ⋃/⋂, so an unshown ``-q`` would under-compute it — sounder than the spec's letter, which omits
      the unknown-binding form; reconciliation ledgered), or ``no`` with a **non-empty** set (an
      empty ``no`` set is vacuously satisfiable without ``-q``: rule 4's "non-empty" carve-out).

    A ``yes`` query reads only the positive literal, covered by the §2.0/RR9 shown-vocabulary
    precondition (deferred), not this rule. Keyed by full ``(name, arity)`` signature, so a contrary
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
    """The ``(sign-aware-name, arity)`` signature of a ground literal, matching ``#show`` vocabulary
    (§2.0)."""
    name = literal.name if literal.positive else f"-{literal.name}"
    return (name, len(literal.arguments))


def _goal_contrary_signature(goal: QueryLiteral) -> tuple[str, int]:
    """The ``(sign-aware-name, arity)`` of a binding goal's *contrary* literal (§2.2 rule 4):
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
