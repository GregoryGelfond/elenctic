"""What elenctic says about itself: its version, licence and holder, and the solvers it runs on.

The version and the licence come from the metadata of the installed package, the holder from its
authors, and the year is the one constant here. A test compares the year and the holder to the
copyright line of `LICENSE`, so they cannot drift apart.
"""

from dataclasses import dataclass
from importlib.metadata import metadata
from typing import Final

DISTRIBUTION: Final = "elenctic"
"""The name the package is installed under."""
YEAR: Final = 2026
"""The year of the copyright line."""


@dataclass(frozen=True, slots=True)
class Package:
    """The package as its metadata and its copyright line state it."""

    version: str
    licence: str
    """An SPDX expression, as the metadata states it."""
    holder: str
    year: int


@dataclass(frozen=True, slots=True)
class Solvers:
    """The versions of the solver modules loaded, which the installed metadata could misstate."""

    clingo: str
    clingcon: str | None
    """`None` when clingcon is not installed."""


def package() -> Package:
    """Read the package: an error if the metadata lacks a field, since each has one source."""
    installed = metadata(DISTRIBUTION)
    return Package(installed["Version"], installed["License-Expression"], installed["Author"], YEAR)
