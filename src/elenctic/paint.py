"""The only place that writes an escape sequence: a role in, styled text out."""

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


_RESET = "\x1b[0m"


def paint(color: Color, role: Role, text: str) -> str:
    """`text` in the style of `role`, if `color` is on."""
    return f"\x1b[{role.value}m{text}{_RESET}" if color is Color.ON else text
