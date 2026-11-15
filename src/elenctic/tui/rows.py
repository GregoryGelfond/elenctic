"""A row as Rich text: the one place a phrase meets Textual.

A row is painted as the text view paints it and read back, so each role's SGR value stays the only
style table, and `NO_COLOR` or `--color never` leave the text plain.
"""

from rich.text import Text

from elenctic.paint import Phrase, paint
from elenctic.presentation import Style
from elenctic.tui.outline import Row


def _lead(lead: Phrase, style: Style) -> str:
    """Paint a lead as it is: a glyph or a margin, which is never made legible."""
    return "".join(
        piece.text if piece.role is None else paint(style.color, piece.role, piece.text)
        for piece in lead
    )


def painted(row: Row, style: Style) -> str:
    """Write a row as the text view writes its line, without the guides: the lead, then the phrase.

    A step's words follow its label after two spaces.
    """
    if row.ansi is not None:
        return row.ansi
    gap = "  " if row.words else ""
    return f"{_lead(row.lead, style)}{style.text(row.phrase)}{gap}{style.text(row.words)}"


def text(row: Row, style: Style) -> Text:
    """Make a row Rich text, by reading back what painting it wrote."""
    return Text.from_ansi(painted(row, style))


def lines(phrases: tuple[Phrase, ...], style: Style) -> Text:
    """Make phrases Rich text, one line each."""
    return Text.from_ansi("\n".join(style.text(phrase) for phrase in phrases))
