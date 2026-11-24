"""The surface syntax of literal lists: patterns with or without default negation, and equations."""

from collections.abc import Iterable
from dataclasses import dataclass

from clingo.ast import AST, ASTType, ComparisonOperator, Sign

from elenctic import tree
from elenctic.body import place, prefixed, read_body, span_of
from elenctic.determination import Valuation
from elenctic.literals import Assumption, Literal, Scenario, Symbol, integer
from elenctic.normalize import NotAPattern, evaluate, function_of, normalize
from elenctic.patterns import Pattern
from elenctic.spans import Diagnostic, Parsed, Position, Span, failure


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


def _item(where: Span, literal: AST, source: str) -> Parsed[Item]:
    span = place(where, span_of(literal, source))
    simple = (
        tree.kind(literal) is ASTType.Literal
        and tree.kind(tree.child(literal, "atom")) is ASTType.SymbolicAtom
    )
    pattern = _pattern(tree.child(literal, "atom")) if simple else None
    sign = tree.number(literal, "sign") if simple else Sign.NoSign
    if isinstance(pattern, NotAPattern):
        return failure(span, f"`{pattern.term}` is not a pattern", label=pattern.reason)
    if pattern is None or sign == Sign.DoubleNegation:
        return failure(span, f"expected a literal, found `{literal}`", label="expected a literal")
    return Item(pattern, sign == Sign.Negation, span)


def literals(items: Iterable[Item]) -> list[Literal] | None:
    """Return the literals the items spell, or `None` unless every one is ground."""
    found = [item.pattern.as_literal() for item in items]
    return None if None in found else [lit for lit in found if lit is not None]


def positive(items: Iterable[Item]) -> list[Literal] | None:
    """Return the literals the items spell, or `None` unless all are ground and without `not`."""
    kept = tuple(items)
    return None if any(item.negated for item in kept) else literals(kept)


def read_literals(text: str, where: Span) -> Parsed[tuple[Item, ...]]:
    """Read a comma-separated list of literals written at `where`."""
    body = read_body(text, where)
    source = prefixed(text)
    return (
        body if isinstance(body, Diagnostic) else _all(_item(where, each, source) for each in body)
    )


def read_valuations(text: str, where: Span) -> Parsed[tuple[Valuation, ...]]:
    """Read a comma-separated list of `term=integer` written at `where`."""
    body = read_body(text, where)
    source = prefixed(text)
    return (
        body
        if isinstance(body, Diagnostic)
        else _all(_valuation(where, each, source) for each in body)
    )


def _all[T](parsed: Iterable[Parsed[T]]) -> Parsed[tuple[T, ...]]:
    """Gather what was read, or the first thing that failed to read."""
    read = list(parsed)
    return next((p for p in read if isinstance(p, Diagnostic)), None) or tuple(
        p for p in read if not isinstance(p, Diagnostic)
    )


def _valuation(where: Span, literal: AST, source: str) -> Parsed[Valuation]:
    return _equation(literal) or failure(
        place(where, span_of(literal, source)),
        f"expected `term = integer`, found `{literal}`",
        label="expected `term = integer`",
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
        number = integer(value)
        return None if number is None else Valuation(variable, number)
    return None


def asked(text: str, source: str) -> tuple[str, Span]:
    """Place what a command was given as its own one-line source, without enclosing braces."""
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        stripped = stripped[1:-1]
    return stripped, Span(source, Position(1, 1), Position(1, len(text) + 1))


def read_asked(text: str, source: str) -> Parsed[tuple[Literal, bool]]:
    """Read the one ground literal a command asks about, and whether `not` was written before it.

    Whether the atom holds is the answer set's to say, so `not p` asks what `p` does; the `not` is
    kept only to head the answer as it was asked.
    """
    body, where = asked(text, source)
    items = read_literals(body, where)
    if isinstance(items, Diagnostic):
        return items
    if len(items) != 1:
        given = f"`{text}`" if items else "nothing"
        return failure(where, f"expected one atom, found {given}", label="expected one atom")
    grounds = literals(items)
    if not grounds:
        return failure(where, "atom asked about is not ground", label="has a variable")
    return grounds[0], items[0].negated


def read_scenario(text: str, source: str) -> Parsed[Scenario]:
    """Read comma-separated assumptions, `p` or `not p`, as `assuming { … }` writes them."""
    body, where = asked(text, source)
    items = read_literals(body, where)
    if isinstance(items, Diagnostic):
        return items
    return scenario_of(items, where)


def scenario_of(items: tuple[Item, ...], where: Span) -> Parsed[Scenario]:
    """Take literals read as assumptions, `not` saying one is taken not to hold."""
    grounds = literals(items)
    if grounds is None:
        return failure(
            where,
            "assumption is not ground",
            label="has a variable",
            notes=("an assumption is a ground literal",),
        )
    return frozenset(
        Assumption(literal, holds=not item.negated)
        for literal, item in zip(grounds, items, strict=True)
    )
