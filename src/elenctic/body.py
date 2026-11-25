"""The text of a tag read as the body of a rule: the literals of a comma-separated list."""

import re
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
    in_code,
    one_line,
)

PREFIX: Final = ":- "

_INCLUDE: Final = re.compile(r"#include\b")


def prefixed(text: str) -> str:
    """Return the rule body clingo sees when reading a comma-separated list.

    Its full stop stands on a line of its own, so a comment that ends the text leaves it be.
    """
    return PREFIX + text + "\n."


def span_of(node: AST, text: str) -> Span:
    """Return where clingo says `node` is, with columns counted in Unicode scalars."""
    return in_characters(tree.span(node), text)


def place(where: Span, inner: Span) -> Span:
    """Place a span read from `PREFIX + text` where `text` was written."""

    def unprefixed(at: Position) -> Position:
        return Position(at.line, at.column - len(PREFIX) if at.line == 1 else at.column)

    return Span(where.source, unprefixed(inner.start), unprefixed(inner.end)).shifted(where.start)


def _first_error(
    where: Span, messages: list[str], text: str, refused: frozenset[str]
) -> Diagnostic:
    lines = prefixed(text).split("\n")
    ends = Position(len(lines), len(lines[-1]))
    found = diagnose("".join(messages), prefixed(text), ends, refused=refused)[0]
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


def _position(text: str, index: int) -> Position:
    """Return where the character at `index` of `text` stands, line and column from 1."""
    return Position(text.count("\n", 0, index) + 1, index - text.rfind("\n", 0, index))


def _included(text: str, where: Span) -> Diagnostic | None:
    """Refuse an `#include` in `text`, before clingo's reader opens the file it names."""
    code = in_code(text)
    found = next((each for each in _INCLUDE.finditer(text) if code[each.start()]), None)
    if found is None:
        return None
    start, end = _position(text, found.start()), _position(text, found.end())
    return failure(
        Span(where.source, start, end).shifted(where.start),
        "expected a literal, found `#include`",
        label="no file is included here",
    )


def read_body(
    text: str, where: Span, *, refused: frozenset[str] = frozenset()
) -> Parsed[tuple[AST, ...]]:
    """Read `text` as the body of a rule, the literals of a comma-separated list.

    A syntax error offers none of the tokens in `refused`, which the caller turns away. An
    `#include` is refused unread: clingo's reader would open the file, wherever it is.
    """
    if (unlexable := first_unlexable(text, where.source)) is not None:
        if unlexable.span is None:
            return unlexable
        return replace(unlexable, span=unlexable.span.shifted(where.start))
    if (included := _included(text, where)) is not None:
        return included
    statements: list[AST] = []
    errors: list[str] = []
    source = prefixed(text)
    try:
        parse_string(source, statements.append, logger=lambda _c, m: errors.append(m))
    except RuntimeError:
        return _first_error(where, errors, text, refused)
    statements = [s for s in statements if tree.kind(s) not in {ASTType.Program, ASTType.Comment}]
    if len(statements) != 1:
        shown = one_line(text) or "{ }"
        return failure(where, f"expected a list of literals, found `{shown}`")
    return tree.children(statements[0], "body")
