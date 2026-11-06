"""Where things are: positions and spans in a source, and the diagnostics attached to them."""

import re
from dataclasses import dataclass
from enum import StrEnum, auto
from typing import Final, override


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A point in a source; line and column both count from 1."""

    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Span:
    """The half-open stretch of `source` from `start` to `end`."""

    source: str
    start: Position
    end: Position

    @override
    def __str__(self) -> str:
        end = self.end
        tail = f"{end.column}" if end.line == self.start.line else f"{end.line}:{end.column}"
        return f"{self.source}:{self.start.line}:{self.start.column}-{tail}"

    def shifted(self, origin: Position) -> Span:
        """Place this span, read as relative to `origin`, in the enclosing source."""
        return Span(self.source, _shift(self.start, origin), _shift(self.end, origin))


def _shift(position: Position, origin: Position) -> Position:
    return Position(
        origin.line + position.line - 1,
        position.column + (origin.column - 1 if position.line == 1 else 0),
    )


class Severity(StrEnum):
    """How serious a diagnostic is."""

    ERROR = auto()
    WARNING = auto()
    NOTE = auto()
    HELP = auto()


@dataclass(frozen=True, slots=True)
class Child:
    """A note or help attached to a diagnostic."""

    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A message about a span, or about the whole source when `span` is none."""

    span: Span | None
    severity: Severity
    message: str
    label: str = ""
    children: tuple[Child, ...] = ()


type Parsed[T] = T | Diagnostic


def failure(
    where: Span | None,
    message: str,
    *,
    label: str = "",
    notes: tuple[str, ...] = (),
    help: tuple[str, ...] = (),  # noqa: A002
) -> Diagnostic:
    """Say that something at `where` is wrong."""
    children = tuple(Child(Severity.NOTE, note) for note in notes) + tuple(
        Child(Severity.HELP, tip) for tip in help
    )
    return Diagnostic(where, Severity.ERROR, message, label, children)


def note(where: Span | None, message: str) -> Diagnostic:
    """Say something about `where` that does not fail the run."""
    return Diagnostic(where, Severity.NOTE, message)


def one_line(text: str) -> str:
    """Put text written over several comment lines on one line, single-spaced."""
    return " ".join(text.split())


def char_column(line: str, byte_column: int) -> int:
    """Map a 1-based UTF-8 byte column to a 1-based Unicode scalar column."""
    if byte_column <= 1:
        return 1
    target = byte_column - 1
    offset = 0
    for index, character in enumerate(line):
        if offset >= target:
            return index + 1
        offset += len(character.encode())
    return len(line) + 1


def _line_at(text: str, number: int) -> str:
    lines = text.split("\n")
    return lines[number - 1] if 1 <= number <= len(lines) else ""


def in_characters(span: Span, text: str) -> Span:
    """Rewrite a span whose columns count UTF-8 bytes so they count Unicode scalars."""
    start = Position(
        span.start.line, char_column(_line_at(text, span.start.line), span.start.column)
    )
    end = Position(span.end.line, char_column(_line_at(text, span.end.line), span.end.column))
    return Span(span.source, start, end)


_ASCII_MAX = 127


def _skip_block_comment(text: str, start: int, mask: list[bool]) -> int:
    mask[start] = mask[start + 1] = False
    index = start + 2
    length = len(text)
    while index < length:
        mask[index] = False
        if text[index] == "*" and index + 1 < length and text[index + 1] == "%":
            mask[index + 1] = False
            return index + 2
        index += 1
    return index


def _skip_line_comment(text: str, start: int, mask: list[bool]) -> int:
    index = start
    length = len(text)
    while index < length and text[index] != "\n":
        mask[index] = False
        index += 1
    return index


def _skip_string(text: str, start: int, mask: list[bool]) -> int:
    mask[start] = False
    index = start + 1
    length = len(text)
    while index < length:
        mask[index] = False
        current = text[index]
        if current == "\\" and index + 1 < length:
            mask[index + 1] = False
            index += 2
            continue
        index += 1
        if current == '"':
            break
    return index


def in_code(text: str) -> list[bool]:
    """Mark each character that sits outside strings and comments."""
    mask = [True] * len(text)
    index, length = 0, len(text)
    while index < length:
        character = text[index]
        if character == "%" and index + 1 < length and text[index + 1] == "*":
            index = _skip_block_comment(text, index, mask)
        elif character == "%":
            index = _skip_line_comment(text, index, mask)
        elif character == '"':
            index = _skip_string(text, index, mask)
        else:
            index += 1
    return mask


def first_unlexable(text: str, source: str) -> Diagnostic | None:
    """Return a diagnostic for the first non-ASCII outside a string or comment.

    Clingo's lexer accepts only ASCII there. With a Python logger, a rejected character makes
    pyclingo abort the process; elenctic refuses the text first so that never happens.
    """
    code = in_code(text)
    line, column = 1, 1
    for index, character in enumerate(text):
        if code[index] and ord(character) > _ASCII_MAX:
            where = Span(source, Position(line, column), Position(line, column + 1))
            shown = character if character.isprintable() else f"U+{ord(character):04X}"
            return failure(
                where,
                f"expected an ASCII character, found `{shown}`",
                label="outside strings and comments",
                help=("clingo's lexer rejects non-ASCII here; keep it in a string or a comment",),
            )
        if character == "\n":
            line += 1
            column = 1
        else:
            column += 1
    return None


_HEADER: Final = re.compile(
    r"(?P<source>.+?):(?P<line>\d+):(?P<column>\d+)"
    r"(?:-(?P<end_line>\d+):(?P<end_column_far>\d+)|-(?P<end_column>\d+))?"
    r": (?P<severity>error|warning|info|note): (?P<message>.*)"
)
_SEVERITY: Final = {"error": Severity.ERROR, "warning": Severity.WARNING}


def _diagnostic(header: re.Match[str], continuation: list[str], text: str | None) -> Diagnostic:
    start = Position(int(header["line"]), int(header["column"]))
    end = Position(
        int(header["end_line"] or start.line),
        int(header["end_column_far"] or header["end_column"] or start.column),
    )
    span = Span(header["source"], start, end)
    if text is not None:
        span = in_characters(span, text)
    children = tuple(Child(Severity.NOTE, line) for line in continuation if line.strip())
    return Diagnostic(
        span,
        _SEVERITY.get(header["severity"], Severity.NOTE),
        header["message"],
        children=children,
    )


def diagnose(message: str, text: str | None = None) -> tuple[Diagnostic, ...]:
    """Read clingo's text for a problem as one diagnostic per located line.

    Clingo counts columns in UTF-8 bytes; pass `text` so they become Unicode scalar columns.
    Continuation lines become `note` children of the header they follow.
    """
    lines = message.rstrip("\n").split("\n")
    heads = [(i, found) for i, line in enumerate(lines) if (found := _HEADER.fullmatch(line))]
    bounds = [*(i for i, _ in heads), len(lines)]
    found_all = tuple(
        _diagnostic(found, lines[i + 1 : end], text)
        for (i, found), end in zip(heads, bounds[1:], strict=True)
    )
    return found_all or (failure(None, message.strip()),)
