"""The text of a tag read as the body of a rule: the literals of a comma-separated list."""

from typing import Final

from clingo.ast import AST, ASTType, Location, parse_string

from elenctic import tree
from elenctic.spans import Diagnostic, Parsed, Position, Span, diagnose, failure, in_characters

PREFIX: Final = ":- "


def prefixed(text: str) -> str:
    """Return the rule body clingo sees when reading a comma-separated list."""
    return PREFIX + text + "."


def span_of(location: Location, text: str) -> Span:
    """Return where clingo says `location` is, with columns counted in Unicode scalars."""
    begin, end = location.begin, location.end
    raw = Span(begin.filename, Position(begin.line, begin.column), Position(end.line, end.column))
    return in_characters(raw, text)


def place(where: Span, inner: Span) -> Span:
    """Place a span read from `PREFIX + text` where `text` was written."""

    def unprefixed(at: Position) -> Position:
        return Position(at.line, at.column - len(PREFIX) if at.line == 1 else at.column)

    return Span(where.source, unprefixed(inner.start), unprefixed(inner.end)).shifted(where.start)


def _first_error(where: Span, messages: list[str], source: str) -> Diagnostic:
    found = diagnose("".join(messages), source)[0]
    if found.span is None:
        return failure(where, found.message)
    notes = tuple(child.message for child in found.children)
    return failure(place(where, found.span), found.message, notes=notes)


def read_body(text: str, where: Span) -> Parsed[tuple[AST, ...]]:
    """Read `text` as the body of a rule, the literals of a comma-separated list."""
    statements: list[AST] = []
    errors: list[str] = []
    source = prefixed(text)
    try:
        parse_string(source, statements.append, logger=lambda _c, m: errors.append(m))
    except RuntimeError:
        return _first_error(where, errors, source)
    statements = [s for s in statements if tree.kind(s) is not ASTType.Program]
    if len(statements) != 1:
        shown = text.strip() or "{ }"
        return failure(where, f"expected a list of literals, found `{shown}`")
    return tree.children(statements[0], "body")
