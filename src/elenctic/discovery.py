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
a friendly ``ProgramError`` at the resolved-program inspection, where UTF-8 is enforced once.

A v1 boundary, recorded not silent: the shown vocabulary is keyed by sign-aware **name**, not
``(name, arity)``. An arity mismatch on a queried contrary surfaces downstream as a *loud*
``@query`` FAIL, never a silent wrong PASS; ``program.inspect`` now exposes arity, so the
arity-aware upgrade is a cheap future refinement (ledgered).
"""

from dataclasses import dataclass
from pathlib import Path

from clingo import Symbol

from elenctic.expectation import Expectation, Sat, has_contract, parse_contract
from elenctic.program import ProgramFacts, inspect
from elenctic.query import Answer, BindingQuery, GroundQuery, Query, QueryLiteral
from elenctic.registry import Solver
from elenctic.terms import contrary

__all__ = ["Case", "DiscoveryError", "check_program", "discover"]


class DiscoveryError(Exception):
    """A corpus that violates a discovery-time precondition (§2.2 rule 4 / the R1 theory gate) or an
    explicitly-named contract-free file (spec §1). Loud by design — discovery never silently drops a
    case nor silently mis-classifies one."""


@dataclass(frozen=True, slots=True)
class Case:
    """One case: a contract-bearing ``.lp`` file, its declared solver, parsed contract, and shown
    vocabulary. The program under test is this file plus its resolved ``#include``s — the loader
    resolves them, so ``files`` is just this path. ``shown`` is the sign-aware shown predicate
    vocabulary (e.g. ``{"reachable", "-reachable"}``) read from the resolved program.
    Provenance-rich (dx#2): the parsed ``expectation`` keeps its ``notes``, and
    ``contract_source`` names the case file, so a renderer or docs tool reads it without re-parsing.
    """

    path: Path
    solver: Solver
    expectation: Expectation
    shown: frozenset[str]

    @property
    def contract_source(self) -> Path:
        """The file the contract was parsed from (dx#2 provenance) — the case file itself."""
        return self.path

    @property
    def files(self) -> tuple[Path, ...]:
        """The program the facade loads: the case file (its ``#include``s resolve at load time)."""
        return (self.path,)


def discover(target: Path) -> tuple[Case, ...]:
    """Discover cases under ``target`` (spec §1, §2). A single file is one case (issue #3); a
    directory is walked (sorted, deterministic) for contract-bearing ``.lp`` files. An explicitly
    named contract-free file is loud (never a silent no-op); a contract-free file in a walked
    directory is a library (skipped). Raises :class:`DiscoveryError` on a precondition violation,
    :class:`~elenctic.expectation.ContractError` on a malformed contract, or
    :class:`~elenctic.program.ProgramError` on a bad ``#include`` or non-UTF-8 program.
    """
    if target.is_file():
        text = _read(target)
        if not has_contract(text):
            raise DiscoveryError(
                f"{target}: not a case — it carries no elenctic contract tag (spec §1). A "
                "contract-free .lp is a library (an #include target), not a runnable case."
            )
        return (_make_case(target, text),)
    return tuple(
        _make_case(path, text)
        for path in sorted(target.rglob("*.lp"))
        if has_contract(text := _read(path))
    )


def _read(path: Path) -> str:
    """Read a ``.lp`` file for the contract scan, tolerant of encoding (``errors="replace"``): the
    contract tags are ASCII, so a non-UTF-8 library is skipped and a non-UTF-8 case is rejected
    (friendly) at the resolved-program inspection, where UTF-8 is enforced once."""
    return path.read_text(encoding="utf-8", errors="replace")


def _make_case(path: Path, text: str) -> Case:
    """Build one case from a contract-bearing file: parse the contract (behavioral + declared
    solver, default ``clingo``), inspect the resolved program, enforce the preconditions."""
    contract = parse_contract(text, source=str(path))
    solver: Solver = contract.solver or "clingo"  # the stated default (R1)
    facts = inspect((path,))
    check_program(contract.expectation, facts, solver, path)
    return Case(path, solver, contract.expectation, facts.shown)


def _solver_provides_theory(solver: Solver) -> bool:
    """Whether ``solver`` interprets theory (``&``) atoms — the v1 conservative predicate
    ``theory_in_force ≡ solver == 'clingcon'`` (adjudicated 2026-06-22). The presence/identity
    boundary: presence is derived, identity (which theory) is declared."""
    return solver == "clingcon"


def check_program(
    expectation: Expectation, facts: ProgramFacts, solver: Solver, where: Path
) -> None:
    """Enforce the §2.2-rule-4 preconditions + the R1 theory-presence gate over the **resolved
    program** (``facts``), under the **declared** ``solver``. Loud (``DiscoveryError``), never a
    verdict. R1: a theory atom under a non-theory solver (presence, never identity). R4: a
    theory-bearing contract under a non-theory solver. R2: the optimization gate, the
    ``@cost``-over-``#maximize`` guard, the shown contrary. R1 (program-side) and R4 (contract-side)
    are complementary duals; both are required."""
    if facts.has_theory_atom and not _solver_provides_theory(solver):
        raise DiscoveryError(
            f"{where}: the resolved program has a theory atom (&…), but the solver is {solver}, "
            "which does not interpret it — clingo grounds theory atoms and silently ignores the "
            "constraints (a wrong PASS). Declare @elenctic solver clingcon (spec §4, R1)"
        )
    if not isinstance(expectation, Sat):
        return
    if expectation.requires_theory and not _solver_provides_theory(solver):
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
            names = ", ".join(sorted(missing))
            raise DiscoveryError(
                f"{where}: a no/unknown @query reads the contrary literal(s) {names} off the shown "
                f"⋂/⋃, but they are absent from the shown vocabulary {sorted(facts.shown)} "
                "(spec §2.0/§2.2 rule 4)"
            )


def _contraries_needed(query: Query) -> frozenset[str]:
    """The sign-aware shown names a query reads as *contraries* off ⋂/⋃, which must therefore be
    shown (§2.2 rule 4):

    - a ground ``no``/``unknown`` query needs **every** conjunct's contrary. Under the corrected ∀∃
      "no" (each model may falsify a *different* conjunct, §2.1), any conjunct's contrary may be the
      witness, so requiring all of them is the conservative *sound* reading (it can over-require,
      but never silently passes an unsound case);
    - a binding query needs the goal's contrary when ``unknown`` (its unknown-set reads ``-q`` off
      ⋃/⋂, so an unshown ``-q`` would under-compute it — sounder than the spec's letter, which omits
      the unknown-binding form; reconciliation ledgered), or ``no`` with a **non-empty** set (an
      empty ``no`` set is vacuously satisfiable without ``-q``: rule 4's "non-empty" carve-out).

    A ``yes`` query reads only the positive literal, covered by the §2.0/RR9 shown-vocabulary
    precondition (deferred), not this rule. Names are arity-blind (see the module docstring)."""
    match query:
        case GroundQuery(answer, conjuncts) if answer in {Answer.no, Answer.unknown}:
            return frozenset(_signed_name(contrary(conjunct)) for conjunct in conjuncts)
        case BindingQuery(Answer.unknown, goal, _):
            return frozenset({_goal_contrary_name(goal)})
        case BindingQuery(Answer.no, goal, bindings) if bindings:
            return frozenset({_goal_contrary_name(goal)})
        case _:
            return frozenset()


def _signed_name(literal: Symbol) -> str:
    """The sign-aware predicate name of a ground literal, matching ``#show`` vocabulary (§2.0)."""
    return literal.name if literal.positive else f"-{literal.name}"


def _goal_contrary_name(goal: QueryLiteral) -> str:
    """The sign-aware name of a binding goal's *contrary* literal (§2.2 rule 4): ``-q`` for ``q``,
    ``q`` for ``-q`` — the dual of :func:`_signed_name` for a (non-ground) goal."""
    return f"-{goal.name}" if goal.positive else goal.name


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
