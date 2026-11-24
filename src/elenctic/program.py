"""A program to be asked about, the text of its sources, and the failure of asking."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum, auto
from os import PathLike
from pathlib import Path
from typing import Final, Self

from elenctic.spans import Diagnostic, Span, in_characters, split_lines

TEXT: Final = "<string>"
"""The name clingo gives a program read from text rather than a file."""


@dataclass(frozen=True, slots=True)
class Source:
    """The text of each source a program reads, by the name clingo reports it under and its own."""

    name: str
    texts: Mapping[str, str]

    def placed(self, reported: Span) -> Span:
        """Return where a span clingo reports is: under the program's name, in Unicode columns."""
        placed = replace(reported, source=self.name) if reported.source == TEXT else reported
        text = self.texts.get(reported.source, self.texts.get(placed.source))
        return placed if text is None else in_characters(placed, text)

    def text(self, span: Span) -> str:
        """Return the source text a span covers, or `""` when the source is not at hand."""
        text = self.texts.get(span.source)
        if text is None:
            return ""
        lines = split_lines(text)
        if not 1 <= span.start.line <= span.end.line <= len(lines):
            return ""
        if span.start.line == span.end.line:
            return lines[span.start.line - 1][span.start.column - 1 : span.end.column - 1]
        first = lines[span.start.line - 1][span.start.column - 1 :]
        middle = lines[span.start.line : span.end.line - 1]
        last = lines[span.end.line - 1][: span.end.column - 1]
        return "\n".join([first, *middle, last])


@dataclass(frozen=True, slots=True)
class Program:
    """ASP source text, and where it came from; `path` makes `#include` resolve beside it."""

    text: str
    source: str = TEXT
    path: Path | None = None
    libraries: tuple[Path, ...] = ()
    """Files loaded after the text, as clingo loads the files it is given: a base encoding."""

    @classmethod
    def read(cls, path: str | PathLike[str], libraries: Iterable[str | PathLike[str]] = ()) -> Self:
        file = Path(path)
        return cls(file.read_text(encoding="utf-8"), str(file), file, tuple(map(Path, libraries)))


class Locus(StrEnum):
    """Whose fault a failure is."""

    PROGRAM = auto()
    REQUEST = auto()


@dataclass(frozen=True, slots=True)
class Fault:
    """A failure that is no answer about the program: it could not be asked."""

    locus: Locus
    diagnostics: tuple[Diagnostic, ...]
