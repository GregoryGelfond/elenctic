"""The only place that writes an escape sequence: a role in, styled text out."""

from dataclasses import dataclass
from enum import Enum


class Color(Enum):
    """Styled text on or off for a stream; resolved once, never asked of a renderer."""

    OFF = "off"
    """Plain text, with no escape sequence."""
    ON = "on"
    """ANSI escape sequences for the roles."""


class Role(Enum):
    """The role of a piece of text; the value is its SGR parameters."""

    ERROR = "1;31"
    WARNING = "1;33"
    NOTE = "1;32"
    HELP = "1;36"
    MARGIN = "1;34"
    EMPHASIS = "1"
    ASIDE = "3"
    """Italic: what qualifies a line of evidence, such as a substitution or a guard."""
    REFERENCE = "2"
    """Dim: where a line of evidence comes from, such as a rule's line."""


_RESET = "\x1b[0m"


def paint(color: Color, role: Role, text: str) -> str:
    """`text` in the style of `role`, if `color` is on."""
    return f"\x1b[{role.value}m{text}{_RESET}" if color is Color.ON else text


@dataclass(frozen=True, slots=True)
class Piece:
    """Text and the role it is shown in; with no role, it is shown as it is."""

    text: str
    role: Role | None = None


type Phrase = tuple[Piece, ...]
"""Pieces shown one after another, each styled by its role."""


def plain(phrase: Phrase) -> str:
    """Write the text of a phrase, unstyled."""
    return "".join(piece.text for piece in phrase)
