"""The glyph table: each Nerd Font glyph beside the plain text it stands for."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from elenctic.verdicts import Verdict


class Glyphs(Enum):
    """Which form of a glyph a stream shows."""

    PLAIN = "plain"
    NERD = "nerd"


@dataclass(frozen=True, slots=True)
class Glyph:
    """A Nerd Font glyph (a private-use code point) and the plain text that stands in for it."""

    nerd: str
    plain: str

    def shown(self, glyphs: Glyphs) -> str:
        return self.nerd if glyphs is Glyphs.NERD else self.plain


MARKS: Final[Mapping[Verdict, Glyph]] = {
    verdict: Glyph(nerd, f"[{verdict.name}]")
    for verdict, nerd in (
        (Verdict.PASS, "\uf058"),
        (Verdict.FAIL, "\uf057"),
        (Verdict.UNDECIDED, "\uf059"),
    )
}
"""The mark of a verdict on a claim: Nerd Fonts 3.5.1 `fa-check_circle`, `fa-times_circle`,
`fa-question_circle`."""
