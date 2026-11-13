"""A glyph: a Nerd Font glyph beside the plain text it stands for; the legend says which to show."""

from dataclasses import dataclass
from enum import Enum


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
