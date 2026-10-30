"""The surface syntax of literal lists and binding sets, read by clingo's own parser."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from clingo import MessageCode, Symbol, SymbolType, parse_term
from clingo.ast import (
    AST,
    ASTType,
    ComparisonOperator,
    Location,
    Sign,
    parse_string,
)

from elenctic.determination import Valuation
from elenctic.normalize import NotAPattern, function_of, normalize
from elenctic.patterns import Pattern
from elenctic.spans import Diagnostic, Position, Severity, Span, diagnose

type Parsed[T] = T | Diagnostic

_PREFIX: Final = ":- "


def _silent(_code: MessageCode, message: str) -> None:
    """Swallow clingo's report; the failure itself raises."""


@dataclass(frozen=True, slots=True)
class Item:
    """One element of a literal list: a pattern, with or without default negation."""

    pattern: Pattern
    negated: bool
    span: Span


def _span(location: Location) -> Span:
    begin, end = location.begin, location.end
    return Span(begin.filename, Position(begin.line, begin.column), Position(end.line, end.column))


def _place(where: Span, inner: Span) -> Span:
    """Place a span read from `_PREFIX + text` where `text` was written."""

    def unprefixed(at: Position) -> Position:
        return Position(at.line, at.column - len(_PREFIX) if at.line == 1 else at.column)

    return Span(where.source, unprefixed(inner.start), unprefixed(inner.end)).shifted(where.start)


def _failure(where: Span, message: str, span: Span | None = None) -> Diagnostic:
    return Diagnostic(span or where, Severity.ERROR, message)


def _symbol(term: AST) -> Symbol | None:
    """Return the ground term `term` is, or `None` if it is anything else."""
    try:
        return parse_term(str(term), _silent)
    except RuntimeError:
        return None


def _pattern(atom: AST) -> Pattern | NotAPattern | None:
    """Read an atom as a pattern, `None` if it is no atom with arguments to read."""
    found = function_of(atom.symbol)
    if found is None:
        return None
    function, positive = found
    arguments = [normalize(argument) for argument in function.arguments]
    refused = next((a for a in arguments if isinstance(a, NotAPattern)), None)
    if refused is not None:
        return refused
    terms = tuple(a for a in arguments if not isinstance(a, NotAPattern))
    return Pattern(function.name, terms, positive=positive)


def _item(where: Span, literal: AST) -> Parsed[Item]:
    span = _place(where, _span(literal.location))
    simple = literal.ast_type is ASTType.Literal and literal.atom.ast_type is ASTType.SymbolicAtom
    pattern = _pattern(literal.atom) if simple else None
    if isinstance(pattern, NotAPattern):
        return _failure(where, str(pattern), span)
    if pattern is None or literal.sign == Sign.DoubleNegation:
        return _failure(where, "expected a literal", span)
    return Item(pattern, literal.sign == Sign.Negation, span)


def _first_error(where: Span, messages: list[str]) -> Diagnostic:
    found = diagnose("".join(messages))[0]
    return _failure(where, found.message, _place(where, found.span))


def _body(text: str, where: Span) -> Parsed[tuple[AST, ...]]:
    """Read `text` as the body of a rule, the literals of a comma-separated list."""
    statements: list[AST] = []
    errors: list[str] = []
    try:
        parse_string(_PREFIX + text + ".", statements.append, logger=lambda _c, m: errors.append(m))
    except RuntimeError:
        return _first_error(where, errors)
    statements = [s for s in statements if s.ast_type is not ASTType.Program]
    if len(statements) != 1:
        return _failure(where, "expected a list of literals")
    return tuple(statements[0].body)


def read_literals(text: str, where: Span) -> Parsed[tuple[Item, ...]]:
    """Read a comma-separated list of literals written at `where`."""
    body = _body(text, where)
    return body if isinstance(body, Diagnostic) else _all(_item(where, each) for each in body)


def read_valuations(text: str, where: Span) -> Parsed[tuple[Valuation, ...]]:
    """Read a comma-separated list of `term=integer` written at `where`."""
    body = _body(text, where)
    return body if isinstance(body, Diagnostic) else _all(_valuation(where, each) for each in body)


def _all[T](parsed: Iterable[Parsed[T]]) -> Parsed[tuple[T, ...]]:
    """Gather what was read, or the first thing that failed to read."""
    read = list(parsed)
    return next((p for p in read if isinstance(p, Diagnostic)), None) or tuple(
        p for p in read if not isinstance(p, Diagnostic)
    )


def _valuation(where: Span, literal: AST) -> Parsed[Valuation]:
    return _equation(literal) or _failure(
        where, "expected `term = integer`", _place(where, _span(literal.location))
    )


def _equation(literal: AST) -> Valuation | None:
    """Read `term = integer` from a body literal, or None when it is anything else."""
    atom = literal.atom
    if literal.ast_type is not ASTType.Literal or atom.ast_type is not ASTType.Comparison:
        return None
    if literal.sign != Sign.NoSign or len(atom.guards) != 1:
        return None
    guard = atom.guards[0]
    variable, value = _symbol(atom.term), _symbol(guard.term)
    equal = guard.comparison == ComparisonOperator.Equal
    if equal and isinstance(variable, Symbol) and isinstance(value, Symbol):
        return Valuation(variable, value.number) if value.type is SymbolType.Number else None
    return None


def read_bindings(text: str, arity: int, where: Span) -> Parsed[tuple[tuple[Symbol, ...], ...]]:
    """Read a set of binding tuples; one variable lists bare terms, several list tuples."""
    if not text.strip():
        return ()
    try:
        term = parse_term(f"({text})", _silent)
    except RuntimeError:
        return _failure(where, "expected a set of terms")
    return _bindings(tuple(term.arguments) if _is_tuple(term) else (term,), arity, where)


def _bindings(
    raw: tuple[Symbol, ...], arity: int, where: Span
) -> Parsed[tuple[tuple[Symbol, ...], ...]]:
    if arity == 1:
        return tuple((element,) for element in raw)
    if all(_is_tuple(element) and len(element.arguments) == arity for element in raw):
        return tuple(tuple(element.arguments) for element in raw)
    if len(raw) == arity and not any(_is_tuple(element) for element in raw):
        return (raw,)
    return _failure(where, f"expected bindings of {arity} terms each")


def _is_tuple(term: Symbol) -> bool:
    return term.type is SymbolType.Function and term.name == "" and bool(term.arguments)
