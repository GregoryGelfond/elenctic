"""Resolved-program inspection — the program-level facts read from the *resolved* AST (the case file
plus its ``#include``s), the shared fix vector for R1 (theory presence) and R2 (preconditions over
the resolved program, spec §3).

One ``clingo.ast.parse_files`` pass (spike-confirmed 2026-06-25): ``parse_files`` resolves
``#include`` relative to the including file and exposes the included nodes in the AST, so the
case-file-text regex scan (which the migration of ``#show``/``#minimize`` into libraries would
defeat) is retired. Theory **presence** only — never identity (the gate is theory-agnostic).
Principle: *contract-level facts read the case file; program-level facts read the resolved program.*
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from clingo.ast import AST, ASTType, UnaryOperator
from clingo.ast import parse_files as _parse_files

from elenctic.result import HarnessError


class ProgramError(HarnessError):
    """A resolved program elenctic cannot load — a missing/cyclic ``#include`` or a parse error.
    Surfaced as a friendly diagnostic naming the offending file, never a raw clingo stack trace
    (R11). A ``HarnessError`` (never a verdict)."""


@dataclass(frozen=True, slots=True)
class ProgramFacts:
    """The program-level facts the §2.2-rule-4 preconditions and the R1 theory gate read.

    ``has_theory_atom`` — any ``&``-atom in the resolved program (R1: presence, not identity).
    ``shown`` — the sign-aware shown predicate names (``{"reachable", "-reachable"}``); empty for a
    bare ``#show.`` (show-nothing). ``has_optimization`` — a ``#minimize``/``#maximize``/``:~`` is
    present. ``has_maximize`` — at least one objective uses ``#maximize`` (a negated-weight
    ``Minimize`` node), which v1 cannot present a natural ``@cost`` over (the guarded miscompile).
    """

    has_theory_atom: bool
    shown: frozenset[str]
    has_optimization: bool
    has_maximize: bool


def inspect(files: tuple[Path, ...]) -> ProgramFacts:
    """Inspect the resolved program (``files`` + their ``#include``s) into ``ProgramFacts``. Raises
    ``ProgramError`` with provenance on an unreadable/missing/cyclic include or a parse error."""
    statements: list[AST] = []
    try:
        _parse_files([str(path) for path in files], statements.append)
    except RuntimeError as exc:
        names = ", ".join(str(path) for path in files)
        raise ProgramError(
            f"cannot resolve the program ({names}): {exc} — check the case's #include paths "
            "(they resolve relative to the including file)"
        ) from exc
    nodes = [node for statement in statements for node in _descendants(statement)]
    return ProgramFacts(
        has_theory_atom=any(node.ast_type is ASTType.TheoryAtom for node in nodes),
        shown=frozenset(name for node in nodes if (name := _shown_name(node))),
        # `#minimize`, `#maximize`, AND `:~` all lower to `Minimize` nodes (confirmed) — one signal.
        has_optimization=any(node.ast_type is ASTType.Minimize for node in nodes),
        has_maximize=any(_is_maximize(node) for node in nodes),
    )


def _descendants(node: object) -> Iterator[AST]:
    """Every ``AST`` node reachable from ``node`` — traversing child attributes AND clingo's
    ``ASTSequence`` (iterable, but **not** a python ``list``; a naive ``isinstance(_, list)`` walk
    misses body literals — the spike's walker bug, now load-bearing for position-robustness)."""
    if isinstance(node, AST):
        yield node
        for key in node.keys():  # noqa: SIM118 - keys() is the AST child-field API, not a dict
            yield from _descendants(getattr(node, key))
    elif not isinstance(node, (str, bytes)) and hasattr(node, "__iter__"):
        for item in node:
            yield from _descendants(item)


def _is_maximize(node: AST) -> bool:
    """A ``#maximize`` objective: clingo lowers it to a ``Minimize`` node whose ``weight`` is a
    negated term (``UnaryOperation`` with ``UnaryOperator.Minus``); ``#minimize`` carries a plain
    ``SymbolicTerm`` weight (confirmed). v1 cannot present a natural ``@cost`` over a negated
    weight, so this is the guard signal. (A ``#minimize`` with an explicitly-negated literal weight
    is structurally identical post-parse and also trips this — correct, and loud-not-silent; full
    sign-tracking lands with the aspis ASP-AST layer.)"""
    return (
        node.ast_type is ASTType.Minimize
        and node.weight.ast_type is ASTType.UnaryOperation
        # `operator_type` is a plain int (0); IntEnum `==` matches, `is` does NOT (confirmed).
        and node.weight.operator_type == UnaryOperator.Minus
    )


def _shown_name(node: AST) -> str | None:
    """The sign-aware shown predicate name a ``#show`` node declares, or ``None`` if it declares no
    predicate (a bare ``#show.`` restricts shown output to nothing). Handles the signature form
    (``#show p/1.`` → ``ShowSignature`` with ``name``/``positive``) and the conditional-term form
    (``#show p(X) : body.`` → ``ShowTerm`` whose ``term`` carries the name). Arity-blind (keyed by
    name only), matching the current contrary logic; ``ShowSignature.arity`` is now available at
    the AST level, so the deferred arity-aware upgrade is cheap (a ledger note, not this scope)."""
    if node.ast_type is ASTType.ShowSignature:
        if not node.name:
            return None
        return node.name if node.positive else f"-{node.name}"
    if node.ast_type is ASTType.ShowTerm:
        return _predicate_name(node.term)
    return None


def _predicate_name(term: AST) -> str | None:
    """The sign-aware predicate name of a shown term: ``p`` / ``-p`` for a (possibly negated)
    function or constant; ``None`` for anything else (a non-predicate term has no name)."""
    if term.ast_type is ASTType.UnaryOperation and term.operator_type == UnaryOperator.Minus:
        inner = _predicate_name(term.argument)
        return f"-{inner}" if inner else None
    if term.ast_type is ASTType.Function:
        return term.name or None
    if term.ast_type is ASTType.SymbolicTerm:
        return getattr(term.symbol, "name", None) or None
    return None
