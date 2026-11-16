"""The interactive view's own parts in the legend's roles: a Textual theme built from `CHROME`.

The rows are painted by `rows`; this colours what Textual draws around them, so each part takes the
colour its role has in the text view, and none with `NO_COLOR` or `--color never`.
"""

from typing import Final

from textual.theme import Theme

from elenctic.legend import CHROME
from elenctic.paint import Color, Role

_ANSI: Final = {
    "31": "ansi_red",
    "32": "ansi_green",
    "33": "ansi_yellow",
    "34": "ansi_blue",
    "36": "ansi_cyan",
}
"""The terminal colour of each SGR colour parameter a role has."""
_TERMINAL: Final = "ansi_default"
_QUIET: Final = "ansi_bright_black"
"""The terminal's grey, which each palette sets apart from its text and its background alike."""
NAME: Final = "elenctic"


def _colored(role: Role) -> str:
    """Name the terminal colour the text view paints `role` in, the terminal's own if none."""
    return next((_ANSI[part] for part in role.value.split(";") if part in _ANSI), _TERMINAL)


def theme(color: Color) -> Theme:
    """Build the theme of the view's parts, in colour when `color` is on and plain when it is not.

    The selected row is shown reversed, as a terminal shows a selection: each piece swaps its
    colour with the background, so it reads as well as it does unselected in any palette. A bar of
    one colour cannot: a role's own colour, or the text's, may match it, as blue on blue does.
    """

    def of(role: Role) -> str:
        return _colored(role) if color is Color.ON else _TERMINAL

    frame, key = of(CHROME["frame"]), of(CHROME["key"])
    quiet = _QUIET if color is Color.ON else _TERMINAL
    return Theme(
        name=NAME,
        ansi=True,
        primary=frame,
        secondary=key,
        warning=of(Role.WARNING),
        error=of(Role.ERROR),
        success=of(Role.NOTE),
        accent=key,
        foreground=_TERMINAL,
        background=_TERMINAL,
        surface=_TERMINAL,
        panel=_TERMINAL,
        boost=_TERMINAL,
        variables={
            "ansi-background": _TERMINAL,
            "ansi-foreground": _TERMINAL,
            "block-cursor-foreground": _TERMINAL,
            "block-cursor-background": _TERMINAL,
            "block-cursor-text-style": "reverse",
            "block-cursor-blurred-foreground": _TERMINAL,
            "block-cursor-blurred-background": _TERMINAL,
            "block-cursor-blurred-text-style": "underline",
            "block-hover-background": _TERMINAL,
            "border": frame,
            "border-blurred": frame,
            "scrollbar": quiet,
            "scrollbar-hover": key,
            "scrollbar-active": key,
            "scrollbar-background": _TERMINAL,
            "scrollbar-background-hover": _TERMINAL,
            "scrollbar-background-active": _TERMINAL,
            "scrollbar-corner-color": _TERMINAL,
            "footer-foreground": _TERMINAL,
            "footer-background": _TERMINAL,
            "footer-key-foreground": key,
            "footer-key-background": _TERMINAL,
            "footer-description-foreground": _TERMINAL,
            "footer-description-background": _TERMINAL,
            "footer-item-background": _TERMINAL,
            "input-cursor-foreground": _TERMINAL,
            "input-cursor-background": _TERMINAL,
            "input-cursor-text-style": "reverse",
            "input-selection-background": quiet,
            "input-selection-foreground": _TERMINAL,
        },
    )
