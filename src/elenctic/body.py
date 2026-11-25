"""The text of a tag read as the body of a rule: the literals of a comma-separated list."""

from dataclasses import replace
from typing import Final

from clingo.ast import AST, ASTType, parse_string

from elenctic import tree
from elenctic.spans import (
    Diagnostic,
    Parsed,
    Position,
    Span,
    diagnose,
    failure,
    first_unlexable,
    in_characters,
    one_line,
)

PREFIX: Final = ":- "


def prefixed(text: str) -> str:
    """Return the rule body clingo sees when reading a comma-separated list."""
    return PREFIX + text + "."


def span_of(node: AST, text: str) -> Span:
    """Return where clingo says `node` is, with columns counted in Unicode scalars."""
    return in_characters(tree.span(node), text)


def place(where: Span, inner: Span) -> Span:
    """Place a span read from `PREFIX + text` where `text` was written."""

    def unprefixed(at: Position) -> Position:
        return Position(at.line, at.column - len(PREFIX) if at.line == 1 else at.column)

    return Span(where.source, unprefixed(inner.start), unprefixed(inner.end)).shifted(where.start)


def _first_error(where: Span, messages: list[str], text: str) -> Diagnostic:
    lines = prefixed(text).split("\n")
    ends = Position(len(lines), len(lines[-1]))
    found = diagnose("".join(messages), prefixed(text), ends)[0]
    if found.span is None:
        return failure(where, found.message)
    notes = tuple(child.message for child in found.children)
    return failure(_within(where, text, place(where, found.span)), found.message, notes=notes)


def _within(where: Span, text: str, span: Span) -> Span:
    """Keep a span inside `text`, written at `where`: clingo places the end of its input past it.

    What starts past the text is put on its last character; what ends past it, cut there.
    """
    lines = text.split("\n")
    column = len(lines[-1]) + (where.start.column if len(lines) == 1 else 1)
    end = Position(where.start.line + len(lines) - 1, column)
    if span.start >= end:
        last = Position(end.line, max(1, end.column - 1))
        return Span(where.source, last, end)
    return span if span.end <= end else Span(span.source, span.start, end)


def read_body(text: str, where: Span) -> Parsed[tuple[AST, ...]]:
    """Read `text` as the body of a rule, the literals of a comma-separated list."""
    if (refused := first_unlexable(text, where.source)) is not None:
        if refused.span is None:
            return refused
        return replace(refused, span=refused.span.shifted(where.start))
    statements: list[AST] = []
    errors: list[str] = []
    source = prefixed(text)
    try:
        parse_string(source, statements.append, logger=lambda _c, m: errors.append(m))
    except RuntimeError:
        return _first_error(where, errors, text)
    statements = [s for s in statements if tree.kind(s) is not ASTType.Program]
    if len(statements) != 1:
        shown = one_line(text) or "{ }"
        return failure(where, f"expected a list of literals, found `{shown}`")
    return tree.children(statements[0], "body")
