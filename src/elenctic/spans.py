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
