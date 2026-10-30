"""The text of a tag read as the body of a rule: the literals of a comma-separated list."""

from typing import Final

from clingo.ast import AST, ASTType, Location, parse_string

from elenctic import tree
from elenctic.spans import Diagnostic, Parsed, Position, Severity, Span, diagnose

_PREFIX: Final = ":- "


def span_of(location: Location) -> Span:
    """Return where clingo says `location` is."""
    begin, end = location.begin, location.end
    return Span(begin.filename, Position(begin.line, begin.column), Position(end.line, end.column))


def place(where: Span, inner: Span) -> Span:
    """Place a span read from `_PREFIX + text` where `text` was written."""

    def unprefixed(at: Position) -> Position:
        return Position(at.line, at.column - len(_PREFIX) if at.line == 1 else at.column)

    return Span(where.source, unprefixed(inner.start), unprefixed(inner.end)).shifted(where.start)


def failure(where: Span, message: str, span: Span | None = None) -> Diagnostic:
    """Say what is wrong with the text at `where`, at `span` within it if that is narrower."""
    return Diagnostic(span or where, Severity.ERROR, message)


def _first_error(where: Span, messages: list[str]) -> Diagnostic:
    found = diagnose("".join(messages))[0]
    return failure(where, found.message, place(where, found.span))


def read_body(text: str, where: Span) -> Parsed[tuple[AST, ...]]:
    """Read `text` as the body of a rule, the literals of a comma-separated list."""
    statements: list[AST] = []
    errors: list[str] = []
    try:
        parse_string(_PREFIX + text + ".", statements.append, logger=lambda _c, m: errors.append(m))
    except RuntimeError:
        return _first_error(where, errors)
    statements = [s for s in statements if tree.kind(s) is not ASTType.Program]
    if len(statements) != 1:
        return failure(where, "expected a list of literals")
    return tree.children(statements[0], "body")
