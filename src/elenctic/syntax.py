"""The surface syntax of literal lists: patterns with or without default negation, and equations."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import NamedTuple

from clingo.ast import AST, ASTType, ComparisonOperator, Sign

from elenctic import tree
from elenctic.body import place, prefixed, read_body, span_of
from elenctic.determination import Valuation
from elenctic.literals import Assumption, Literal, Scenario, Symbol, integer
from elenctic.normalize import NotAPattern, evaluate, function_of, normalize
from elenctic.patterns import Pattern
from elenctic.program import Source
from elenctic.spans import Diagnostic, Parsed, Position, Span, failure, one_line


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
    inner = span_of(literal, source)
    span = place(where, inner)
    written = one_line(Source(inner.source, {inner.source: source}).text(inner))
    simple = (
        tree.kind(literal) is ASTType.Literal
        and tree.kind(tree.child(literal, "atom")) is ASTType.SymbolicAtom
    )
    pattern = _pattern(tree.child(literal, "atom")) if simple else None
    sign = tree.number(literal, "sign") if simple else Sign.NoSign
    if isinstance(pattern, NotAPattern):
        return failure(span, f"`{written}` is not one literal", label=pattern.reason)
    if pattern is None or sign == Sign.DoubleNegation:
        return failure(span, f"expected a literal, found `{written}`", label="expected a literal")
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
    sides = _equated(literal)
    if sides is None:
        return None
    variable, value = (evaluate(str(side)) for side in sides)
    if isinstance(variable, Symbol) and isinstance(value, Symbol):
        number = integer(value)
        return None if number is None else Valuation(variable, number)
    return None


def _equated(literal: AST) -> tuple[AST, AST] | None:
    """Read the two sides of `a = b` from a body literal, or None when it is anything else."""
    atom = tree.child(literal, "atom")
    if tree.kind(literal) is not ASTType.Literal or tree.kind(atom) is not ASTType.Comparison:
        return None
    guards = tree.children(atom, "guards")
    if tree.number(literal, "sign") != Sign.NoSign or len(guards) != 1:
        return None
    guard = guards[0]
    if tree.number(guard, "comparison") != ComparisonOperator.Equal:
        return None
    return tree.child(atom, "term"), tree.child(guard, "term")


def read_binding(text: str, variables: tuple[str, ...], source: str) -> Parsed[tuple[Symbol, ...]]:
    """Read a binding of a query's variables as `ask` writes it, `X = a, Y = 1`, in their order.

    Braces and a full stop may enclose and end it, as they do a query. Each variable takes one
    value, and only the query's variables take one.
    """
    body, at, where = asked(text, source)
    read = read_body(body, at)
    if isinstance(read, Diagnostic):
        return read
    values = _values(read, variables, at, prefixed(body))
    if isinstance(values, Diagnostic):
        return values
    missing = next((each for each in variables if each not in values), None)
    if missing is not None:
        bind = f"bind each of the query's variables: `{binding_shape(variables)}`"
        return failure(where, f"the binding gives `{missing}` no value", help=(bind,))
    return tuple(values[each] for each in variables)


def binding_shape(variables: tuple[str, ...]) -> str:
    """Write the shape of a binding of `variables`, `X = …, Y = …`, as `ask` writes one."""
    return ", ".join(f"{each} = \N{HORIZONTAL ELLIPSIS}" for each in variables)


def _values(
    literals: tuple[AST, ...], variables: tuple[str, ...], at: Span, given: str
) -> Parsed[dict[str, Symbol]]:
    """Read the value each `variable = term` gives, refusing anything else where it stands."""
    values: dict[str, Symbol] = {}
    for literal in literals:
        span = place(at, span_of(literal, given))
        pair = _binding(literal)
        if pair is None:
            expected = "expected `variable = term`"
            return failure(span, f"{expected}, found `{literal}`", label=expected)
        name, value = pair
        if name not in variables:
            return failure(
                span, f"`{name}` is not a variable of the query", label="not in the query"
            )
        if name in values:
            return failure(span, f"`{name}` is bound twice", label="bound before")
        values[name] = value
    return values


def _binding(literal: AST) -> tuple[str, Symbol] | None:
    """Read `variable = term` from a body literal, or None when it is anything else."""
    sides = _equated(literal)
    if sides is None or tree.kind(sides[0]) is not ASTType.Variable:
        return None
    value = evaluate(str(sides[1]))
    return None if value is None else (tree.name(sides[0]), value)


class Asked(NamedTuple):
    """What a command was given, without its braces or full stop, and where it stands."""

    text: str
    at: Span
    """Where `text` stands in what was given, so what is read from it is placed there."""
    whole: Span
    """All that was given, for a refusal of it as a whole."""


def asked(given: str, source: str) -> Asked:
    """Place what a command was given as its own one-line source, without braces or full stop.

    A full stop may end it, as one ends a statement; braces may enclose what precedes that.
    """
    lead = len(given) - len(given.lstrip())
    text = given.strip()
    if text.endswith("."):
        text = text[:-1].rstrip()
    if text.startswith("{") and text.endswith("}"):
        text, lead = text[1:-1], lead + 1
    at = Span(source, Position(1, lead + 1), Position(1, lead + len(text) + 1))
    return Asked(text, at, Span.whole(source, given))


def read_asked(text: str, source: str) -> Parsed[tuple[Literal, bool]]:
    """Read the one ground literal a command asks about, and whether `not` was written before it.

    Whether the atom holds is the answer set's to say, so `not p` asks what `p` does; the `not` is
    kept only to head the answer as it was asked.
    """
    body, at, where = asked(text, source)
    items = read_literals(body, at)
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
    body, at, where = asked(text, source)
    items = read_literals(body, at)
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
