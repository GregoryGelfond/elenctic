"""What a program says of itself in its statements: what it shows, and where its theory is."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import reduce
from typing import Final

from clingo import Control, SymbolType
from clingo.ast import AST, ASTType, Location, UnaryOperator

from elenctic import tree
from elenctic.literals import Signature
from elenctic.program import Program
from elenctic.spans import Position, Span


@dataclass(frozen=True, slots=True)
class Shown:
    """The predicates `#show` selects; with no `#show` statement every atom is shown.

    A `#show` of a term with a variable selects what the grounder decides, so it is `wild`.
    """

    signatures: frozenset[Signature] = frozenset()
    restricted: bool = False
    wild: bool = False

    def covers(self, signature: Signature) -> bool:
        return not self.restricted or self.wild or signature in self.signatures

    def __or__(self, other: Shown) -> Shown:
        return Shown(
            self.signatures | other.signatures,
            self.restricted or other.restricted,
            self.wild or other.wild,
        )


@dataclass(frozen=True, slots=True)
class Facts:
    """What the grounded program says about itself, which a contract is checked against.

    `theory` is where the first statement with a theory atom is, if the program has any, and
    `objective` where the first with a theory objective, `&minimize` or `&maximize`, is.
    """

    shown: Shown = Shown()
    optimizes: bool = False
    theory: Span | None = None
    objective: Span | None = None


def _signature(term: AST) -> Signature | None:
    """Read the predicate a `#show` term names; `None` for a term that is not a literal."""
    match tree.kind(term):
        case ASTType.Function:
            return Signature(tree.name(term), len(tree.children(term, "arguments")))
        case ASTType.SymbolicTerm if tree.symbol(term).type is SymbolType.Function:
            symbol = tree.symbol(term)
            return Signature(symbol.name, len(symbol.arguments), symbol.positive)
        case ASTType.UnaryOperation if tree.number(term, "operator_type") == UnaryOperator.Minus:
            inner = _signature(tree.child(term, "argument"))
            return inner and Signature(inner.name, inner.arity, positive=not inner.positive)
        case _:
            return None


def _shown(statement: AST) -> Shown:
    """Read what a statement selects to show; a statement that is no `#show` selects nothing."""
    match tree.kind(statement):
        case ASTType.ShowSignature:
            signature = Signature(
                tree.name(statement),
                tree.number(statement, "arity"),
                tree.flag(statement, "positive"),
            )
            return Shown(frozenset({signature}), restricted=True)
        case ASTType.ShowTerm:
            term = tree.child(statement, "term")
            named = _signature(term)
            return Shown(
                frozenset({named} if named else ()),
                restricted=True,
                wild=tree.kind(term) is ASTType.Variable,
            )
        case _:
            return Shown()


def shown_by(statements: Iterable[AST]) -> Shown:
    """Gather what the statements of a program select to show."""
    return reduce(Shown.__or__, map(_shown, statements), Shown())


def _theoretical(node: AST) -> bool:
    return tree.kind(node) is ASTType.TheoryAtom or any(map(_theoretical, tree.subtrees(node)))


_OBJECTIVES: Final = frozenset({"minimize", "maximize"})


def _objective(node: AST) -> bool:
    """Say whether `node` holds a theory objective: clingcon applies it in every search."""
    named = (
        tree.kind(node) is ASTType.TheoryAtom and tree.name(tree.child(node, "term")) in _OBJECTIVES
    )
    return named or any(map(_objective, tree.subtrees(node)))


def _span(location: Location, program: Program) -> Span:
    begin, end = location.begin, location.end
    source = program.source if begin.filename == "<string>" else begin.filename
    return Span(source, Position(begin.line, begin.column), Position(end.line, end.column))


def _first(
    statements: Iterable[AST], holds: Callable[[AST], bool], program: Program
) -> Span | None:
    """Locate the first statement for which `holds`."""
    found = next((s for s in statements if holds(s)), None)
    return None if found is None else _span(tree.location(found), program)


def theory_at(control: Control, statements: Iterable[AST], program: Program) -> Span | None:
    """Locate the first statement with a theory atom, if grounding left any theory atom."""
    if next(iter(control.theory_atoms), None) is None:
        return None
    return _first(statements, _theoretical, program)


def objective_at(statements: Iterable[AST], program: Program) -> Span | None:
    """Locate the first statement with a theory objective."""
    return _first(statements, _objective, program)
