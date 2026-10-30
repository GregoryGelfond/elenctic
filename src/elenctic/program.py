"""A program to be asked about, and the failure of asking."""

from dataclasses import dataclass
from enum import StrEnum
from os import PathLike
from pathlib import Path
from typing import Self

from elenctic.spans import Diagnostic


@dataclass(frozen=True, slots=True)
class Program:
    """ASP source text, and where it came from; `path` makes `#include` resolve beside it."""

    text: str
    source: str = "<string>"
    path: Path | None = None

    @classmethod
    def read(cls, path: str | PathLike[str]) -> Self:
        file = Path(path)
        return cls(file.read_text(encoding="utf-8"), str(file), file)


class Locus(StrEnum):
    """Whose fault a failure is."""

    PROGRAM = "program"
    REQUEST = "request"


@dataclass(frozen=True, slots=True)
class Fault:
    """A failure that is no answer about the program: it could not be asked."""

    locus: Locus
    diagnostics: tuple[Diagnostic, ...]
