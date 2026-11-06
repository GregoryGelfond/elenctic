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


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A message about a span."""

    span: Span
    severity: Severity
    message: str


type Parsed[T] = T | Diagnostic


def failure(where: Span, message: str) -> Diagnostic:
    """Say that something at `where` is wrong."""
    return Diagnostic(where, Severity.ERROR, message)


def note(where: Span, message: str) -> Diagnostic:
    """Say something about `where` that does not fail the run."""
    return Diagnostic(where, Severity.NOTE, message)


UNLOCATED: Final = Span("", Position(1, 1), Position(1, 1))

_HEADER: Final = re.compile(
    r"(?P<source>.+?):(?P<line>\d+):(?P<column>\d+)"
    r"(?:-(?P<end_line>\d+):(?P<end_column_far>\d+)|-(?P<end_column>\d+))?"
    r": (?P<severity>error|warning|info|note): (?P<message>.*)"
)
_SEVERITY: Final = {"error": Severity.ERROR, "warning": Severity.WARNING}


def _diagnostic(header: re.Match[str], continuation: list[str]) -> Diagnostic:
    start = Position(int(header["line"]), int(header["column"]))
    end = Position(
        int(header["end_line"] or start.line),
        int(header["end_column_far"] or header["end_column"] or start.column),
    )
    return Diagnostic(
        Span(header["source"], start, end),
        _SEVERITY.get(header["severity"], Severity.NOTE),
        "\n".join([header["message"], *continuation]),
    )


def diagnose(message: str) -> tuple[Diagnostic, ...]:
    """Read clingo's text for a problem as one diagnostic per located line."""
    lines = message.rstrip("\n").split("\n")
    heads = [(i, found) for i, line in enumerate(lines) if (found := _HEADER.fullmatch(line))]
    bounds = [*(i for i, _ in heads), len(lines)]
    found_all = tuple(
        _diagnostic(found, lines[i + 1 : end])
        for (i, found), end in zip(heads, bounds[1:], strict=True)
    )
    return found_all or (failure(UNLOCATED, message.strip()),)
