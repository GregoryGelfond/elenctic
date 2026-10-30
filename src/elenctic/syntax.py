"""The surface syntax of literal lists: patterns with or without default negation, and equations."""

from collections.abc import Iterable
from dataclasses import dataclass

from clingo import Symbol, SymbolType
from clingo.ast import AST, ASTType, ComparisonOperator, Sign

from elenctic import tree
from elenctic.body import failure, place, read_body, span_of
from elenctic.determination import Valuation
from elenctic.normalize import NotAPattern, evaluate, function_of, normalize
from elenctic.patterns import Pattern
from elenctic.spans import Diagnostic, Parsed, Span


@dataclass(frozen=True, slots=True)
class Item:
    """One element of a literal list: a pattern, with or without default negation."""

    pattern: Pattern
    negated: bool
    span: Span


def _pattern(atom: AST) -> Pattern | NotAPattern | None:
    """Read an atom as a pattern, `None` if it is no atom with arguments to read."""
    found = function_of(tree.child(atom, "symbol"))
    if found is None:
        return None
    function, positive = found
    arguments = [normalize(argument) for argument in tree.children(function, "arguments")]
    refused = next((a for a in arguments if isinstance(a, NotAPattern)), None)
    if refused is not None:
        return refused
    terms = tuple(a for a in arguments if not isinstance(a, NotAPattern))
    return Pattern(tree.name(function), terms, positive=positive)


def _item(where: Span, literal: AST) -> Parsed[Item]:
    span = place(where, span_of(tree.location(literal)))
    simple = (
        tree.kind(literal) is ASTType.Literal
        and tree.kind(tree.child(literal, "atom")) is ASTType.SymbolicAtom
    )
    pattern = _pattern(tree.child(literal, "atom")) if simple else None
    sign = tree.number(literal, "sign") if simple else Sign.NoSign
    if isinstance(pattern, NotAPattern):
        return failure(where, str(pattern), span)
    if pattern is None or sign == Sign.DoubleNegation:
        return failure(where, "expected a literal", span)
    return Item(pattern, sign == Sign.Negation, span)


def read_literals(text: str, where: Span) -> Parsed[tuple[Item, ...]]:
    """Read a comma-separated list of literals written at `where`."""
    body = read_body(text, where)
    return body if isinstance(body, Diagnostic) else _all(_item(where, each) for each in body)


def read_valuations(text: str, where: Span) -> Parsed[tuple[Valuation, ...]]:
    """Read a comma-separated list of `term=integer` written at `where`."""
    body = read_body(text, where)
    return body if isinstance(body, Diagnostic) else _all(_valuation(where, each) for each in body)


def _all[T](parsed: Iterable[Parsed[T]]) -> Parsed[tuple[T, ...]]:
    """Gather what was read, or the first thing that failed to read."""
    read = list(parsed)
    return next((p for p in read if isinstance(p, Diagnostic)), None) or tuple(
        p for p in read if not isinstance(p, Diagnostic)
    )


def _valuation(where: Span, literal: AST) -> Parsed[Valuation]:
    return _equation(literal) or failure(
        where, "expected `term = integer`", place(where, span_of(tree.location(literal)))
    )


def _equation(literal: AST) -> Valuation | None:
    """Read `term = integer` from a body literal, or None when it is anything else."""
    atom = tree.child(literal, "atom")
    if tree.kind(literal) is not ASTType.Literal or tree.kind(atom) is not ASTType.Comparison:
        return None
    guards = tree.children(atom, "guards")
    if tree.number(literal, "sign") != Sign.NoSign or len(guards) != 1:
        return None
    guard = guards[0]
    variable = evaluate(str(tree.child(atom, "term")))
    value = evaluate(str(tree.child(guard, "term")))
    equal = tree.number(guard, "comparison") == ComparisonOperator.Equal
    if equal and isinstance(variable, Symbol) and isinstance(value, Symbol):
        return Valuation(variable, value.number) if value.type is SymbolType.Number else None
    return None
