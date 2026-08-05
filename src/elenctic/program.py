"""Resolved-program inspection — the program-level facts read from the *resolved* AST (the case file
plus its ``#include``s), the shared fix vector for theory-presence detection and the
preconditions over the resolved program.

One ``clingo.ast.parse_files`` pass: ``parse_files`` resolves
``#include`` relative to the including file and exposes the included nodes in the AST, so the
case-file-text regex scan (which the migration of ``#show``/``#minimize`` into libraries would
defeat) is retired. Theory **presence** only — never identity (the gate is theory-agnostic).
Principle: *contract-level facts read the case file; program-level facts read the resolved program.*
"""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from clingo import SymbolType
from clingo.ast import AST, ASTType, UnaryOperator, parse_files as _parse_files

__all__ = ["ProgramError", "ProgramFacts", "inspect"]


class ProgramError(Exception):
    """A program under test that elenctic cannot run — a missing or cyclic ``#include``, a parse
    error, or a program that will not ground. Surfaced as a friendly diagnostic naming the offending
    file, never a raw clingo stack trace.

    A fault in the program, so its author fixes the ``.lp``; deliberately **not** a
    ``HarnessError``, which claims elenctic violated one of its own invariants and should be
    reported. The two are disjoint roots so that neither can be caught as the other, and neither is
    ever a verdict about the program's answer-set behaviour."""


@dataclass(frozen=True, slots=True)
class ProgramFacts:
    """The program-level facts the preconditions and the theory gate read.

    ``has_theory_atom`` — any ``&``-atom in the resolved program (presence, not identity).
    ``shown`` — the shown predicate **signatures** ``(sign-aware-name, arity)`` (e.g.
    ``{("reachable", 1), ("-reachable", 1)}``); empty for a bare ``#show.`` (show-nothing). Keyed by
    full signature, not name, so a ``@query`` contrary ``#show``n at the wrong arity is a *loud*
    precondition failure, not a silent miss. ``has_optimization`` — a ``#minimize``, ``#maximize``,
    or ``:~`` is present. ``has_maximize`` — an objective uses ``#maximize`` (a negated-weight
    ``Minimize`` node), which v1 cannot present a natural ``@cost`` over (the guarded miscompile).
    ``has_theory_optimization`` — a *theory-native* objective (``&minimize``/``&maximize``) is
    present. It is tracked apart from ``has_optimization`` because it is a different object: the
    theory's own propagator drives it, so clingo's optimization switches do not reach it, and a
    reading of AS(P) cannot be made honest by turning them off.
    ``sources`` — the resolved source files the program spans: the case file plus every file it
    transitively ``#include``s, taken from clingo's own parse (each statement's ``location``), so it
    matches clingo's include resolution exactly (block comments, every include form). The corpus
    orphan-library backstop reads this rather than re-scanning text; only a *truly empty*
    included library (no statements — a comment-only file still yields ``Comment`` nodes) is absent
    and so over-reported as an orphan, the safe direction for a warn-only check.
    """

    has_theory_atom: bool
    shown: frozenset[tuple[str, int]]
    has_optimization: bool
    has_maximize: bool
    has_theory_optimization: bool
    sources: frozenset[Path]


def inspect(files: tuple[Path, ...]) -> ProgramFacts:
    """Inspect the resolved program (``files`` + their ``#include``s) into ``ProgramFacts``. Raises
    ``ProgramError`` with provenance on an unreadable/missing/cyclic include, a parse error, or a
    source byte that is not UTF-8.

    Three phases, because they have three different owners and a region can only name one. The
    parse is clingo's over the corpus author's text, so its failures are the program's. The walk
    over what clingo returned is elenctic's own code — with one exception, since clingo decodes
    node strings *lazily*, so a non-UTF-8 source byte surfaces here rather than at parse. Resolving
    the source names needs no clingo state at all and comes last, outside both regions."""
    statements: list[AST] = []
    messages: list[str] = []  # clingo's own diagnostics (with file:line:col), captured not printed
    with _parse_faults(files, messages):
        _parse_files(
            [str(path) for path in files],
            statements.append,
            logger=lambda _code, message: messages.append(message),
        )
    with _walk_faults(files):
        nodes = [node for statement in statements for node in _descendants(statement)]
        has_theory_atom = any(node.ast_type is ASTType.TheoryAtom for node in nodes)
        shown = frozenset(sig for node in nodes if (sig := _shown_signature(node)))
        # `#minimize`, `#maximize`, AND `:~` all lower to `Minimize` nodes — one signal.
        has_optimization = any(node.ast_type is ASTType.Minimize for node in nodes)
        has_maximize = any(_is_maximize(node) for node in nodes)
        has_theory_optimization = any(_is_theory_objective(node) for node in nodes)
        # Each statement carries the file it came from (clingo's own include resolution); reading
        # that name is a decode, so it belongs here, while resolving it is a question for the
        # filesystem and belongs below.
        filenames = {statement.location.begin.filename for statement in statements}
    return ProgramFacts(
        has_theory_atom=has_theory_atom,
        shown=shown,
        has_optimization=has_optimization,
        has_maximize=has_maximize,
        has_theory_optimization=has_theory_optimization,
        # The distinct set, resolved once each, is the program's authoritative source-file span.
        sources=frozenset(Path(name).resolve() for name in filenames if name),
    )


@contextmanager
def _parse_faults(files: tuple[Path, ...], messages: list[str]) -> Iterator[None]:
    """Translate a failure raised by the parse into a ``ProgramError`` naming the program and
    carrying clingo's own captured diagnostic.

    Everything under this region is clingo reading the corpus author's text, so every failure it
    reports is that author's to fix. A harness-logic bug (``AttributeError``/``KeyError``/...) is
    not caught and stays loud, and ``RecursionError`` is re-raised for the same reason it is in the
    solver facade: it is a ``RuntimeError`` subclass, and it never means the program is at fault.
    Nothing under this region recurses, but the callbacks clingo fires here run on whatever stack
    the caller had left."""
    try:
        yield
    except RecursionError:
        raise
    except UnicodeEncodeError as exc:
        # The file *name*, not its contents: clingo encodes the path strictly, so a name carrying a
        # byte that is not UTF-8 fails before the file is opened. A sibling of UnicodeDecodeError
        # rather than a subclass, so the tuple below does not cover it.
        names = ", ".join(str(path) for path in files)
        raise ProgramError(
            f"cannot open the program ({names}): the file name is not valid UTF-8, which the "
            "solver requires — rename the file"
        ) from exc
    except (RuntimeError, UnicodeDecodeError, OSError) as exc:
        # RuntimeError: a parse / missing-or-cyclic-#include failure (clingo logged the detail to
        # `messages`); UnicodeDecodeError: a source byte reaching Python through a diagnostic;
        # OSError: unreadable.
        names = ", ".join(str(path) for path in files)
        # Both, never one or the other: the logger holds the provenance but accumulates routine
        # notices too, so a fault raised after a clean parse would otherwise be reported as
        # whichever harmless notice was logged first, with the real cause dropped.
        detail = "; ".join([*messages, str(exc)])
        # The include advice is specific enough to act on, so it is offered only when it is the
        # remedy. Attached to a syntax error it sends the author to check paths that are fine.
        hint = (
            " — check the case's #include paths (they resolve relative to the including file)"
            if "could not be opened" in detail
            else ""
        )
        raise ProgramError(f"cannot resolve the program ({names}): {detail}{hint}") from exc


@contextmanager
def _walk_faults(files: tuple[Path, ...]) -> Iterator[None]:
    """Translate the one failure of elenctic's own walk that belongs to the program: a source byte
    that is not valid UTF-8, which clingo decodes lazily and so raises here rather than at parse.

    Anything else raised under this region comes from elenctic's traversal of an AST clingo already
    accepted, and it is elenctic's — so it is left to propagate with its own type, and is reported
    as the defect it is instead of sending a corpus author to fix a file that parsed. That includes
    ``RecursionError``: nothing under this region recurses, so it can no longer describe a term the
    walk could not follow, and it means here what it means in the solver facade. The parse's
    captured diagnostics are deliberately not spliced into these messages: they describe the text,
    and a notice about an atom occurring in no rule head explains nothing about a byte that will
    not decode."""
    try:
        yield
    except UnicodeDecodeError as exc:
        names = ", ".join(str(path) for path in files)
        raise ProgramError(
            f"cannot read the program ({names}): a byte in the source is not valid UTF-8, which "
            f"the solver requires — re-encode the file as UTF-8 ({exc})"
        ) from exc


def _descendants(node: object) -> Iterator[AST]:
    """Every ``AST`` node reachable from ``node`` — traversing child attributes AND clingo's
    ``ASTSequence`` (iterable, but **not** a python ``list``; a naive ``isinstance(_, list)`` walk
    misses body literals).

    An explicit work-list, not recursive delegation. The depth here is decided by the program under
    test, so recursion would bound what elenctic can read by the interpreter's stack — and a term
    nested past it is one clingo grounds and solves without complaint. It is not only a hostile
    shape that reaches it: a list written as ``cons(a, cons(b, …))`` nests one level per element.
    The work-list yields in a different order than recursion would, which no reader depends on —
    each folds these nodes into a set or an existence check."""
    pending: list[object] = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, AST):
            yield current
            # keys() is the AST child-field API, not a dict
            pending.extend(getattr(current, key) for key in current.keys())  # noqa: SIM118
        elif not isinstance(current, (str, bytes)) and hasattr(current, "__iter__"):
            pending.extend(current)


# The theory-native objective directives. clingcon spells its objective `&minimize`/`&maximize`,
# which parse as a TheoryAtom whose term is a plain function of that name — no `Minimize` node, so
# the clingo-native signal never sees them.
_THEORY_OBJECTIVES: Final = frozenset({"minimize", "maximize"})


def _is_theory_objective(node: AST) -> bool:
    """A theory-native objective (``&minimize { … }`` / ``&maximize { … }``): a ``TheoryAtom``
    whose term names one of them. Read by name, since the objective belongs to the theory rather
    than to clingo: no ``Minimize`` node is produced and no clingo optimization flag reaches it.

    The term's type is asked before its name, rather than reading the name with a default to fall
    back on. The fallback would work here — a missing field on an AST node does return the default
    — but relying on it is what hid a defect in the signature reader, where the same expression
    over a *symbol* raises instead, so the default could never fire. Nothing about the two spellings
    distinguishes them at a glance, so neither is written. clingo represents a theory atom's term
    as a function node in every form it accepts, in a head or a body, with arguments or with a
    condition, so asking is total."""
    return (
        node.ast_type is ASTType.TheoryAtom
        and node.term.ast_type is ASTType.Function
        and node.term.name in _THEORY_OBJECTIVES
    )


def _is_maximize(node: AST) -> bool:
    """A ``#maximize`` objective: clingo lowers it to a ``Minimize`` node whose ``weight`` is a
    negated term (``UnaryOperation`` with ``UnaryOperator.Minus``); ``#minimize`` carries a plain
    ``SymbolicTerm`` weight. v1 cannot present a natural ``@cost`` over a negated
    weight, so this is the guard signal. (A ``#minimize`` with an explicitly-negated literal weight
    is structurally identical post-parse and also trips this — correct, and loud-not-silent; full
    sign-tracking is deferred.)"""
    return (
        node.ast_type is ASTType.Minimize
        and node.weight.ast_type is ASTType.UnaryOperation
        # `operator_type` is a plain int (0); IntEnum `==` matches, `is` does NOT.
        and node.weight.operator_type == UnaryOperator.Minus
    )


def _shown_signature(node: AST) -> tuple[str, int] | None:
    """The ``(sign-aware-name, arity)`` signature a ``#show`` node declares, or ``None`` if it
    declares no predicate (a bare ``#show.`` restricts shown output to nothing). Handles the
    signature form (``#show p/1.`` → ``ShowSignature`` with ``name``/``positive``/``arity``) and the
    conditional-term form (``#show p(X) : body.`` → ``ShowTerm`` whose ``term`` carries name +
    arity). Keyed by full signature, so a ``@query`` contrary ``#show``n at the wrong arity is a
    loud precondition failure rather than a silent miss."""
    if node.ast_type is ASTType.ShowSignature:
        if not node.name:
            return None
        name = node.name if node.positive else f"-{node.name}"
        return (name, node.arity)
    if node.ast_type is ASTType.ShowTerm:
        return _predicate_signature(node.term)
    return None


def _predicate_signature(term: AST) -> tuple[str, int] | None:
    """The ``(sign-aware-name, arity)`` of a shown term: ``(p, n)`` / ``(-p, n)`` for a (possibly
    negated) function or constant; ``None`` for anything else (a non-predicate term has no name).

    The negation chain is peeled with a loop for the same reason the node walk uses one: its length
    is the program's to choose, and clingo accepts one far longer than the interpreter would let
    this recurse along. Each sign is kept rather than folded, so the signature records what the
    author wrote."""
    negations = 0
    while term.ast_type is ASTType.UnaryOperation and term.operator_type == UnaryOperator.Minus:
        negations += 1
        term = term.argument
    signature = _unsigned_signature(term)
    if signature is None:
        return None
    name, arity = signature
    return ("-" * negations + name, arity)


def _unsigned_signature(term: AST) -> tuple[str, int] | None:
    """The ``(name, arity)`` of a shown term with its negation chain already peeled: a function or
    constant carries one, anything else carries none."""
    if term.ast_type is ASTType.Function:
        return (term.name, len(term.arguments)) if term.name else None
    if term.ast_type is ASTType.SymbolicTerm:
        # The type is asked before the name, because a symbol's name is defined only for a function
        # symbol: reading one off a string or a number raises rather than reporting that there is
        # none, so a default cannot stand in for it. `#show "text" : p.` and `#show 42 : p.` are
        # both programs clingo runs, and neither declares a predicate.
        symbol = term.symbol
        if symbol.type is not SymbolType.Function:
            return None
        return (symbol.name, len(symbol.arguments)) if symbol.name else None
    return None
