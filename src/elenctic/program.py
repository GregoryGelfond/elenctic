"""A program to be asked about, and the failure of asking."""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import StrEnum, auto
from os import PathLike
from pathlib import Path
from typing import Final, Self

from elenctic.spans import Diagnostic, Span

TEXT: Final = "<string>"
"""The name clingo gives a program read from text rather than a file."""


def named(span: Span, name: str) -> Span:
    """Return `span` under `name` if clingo placed it in the text, else as clingo placed it."""
    return replace(span, source=name) if span.source == TEXT else span


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
