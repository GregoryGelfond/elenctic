"""Making corpus-controlled text safe to show.

Everything elenctic prints about a case is influenced by the case: its path, its ``@note`` prose,
the atoms in its answer sets, and the solver's own diagnostics about it. A corpus is untrusted input
— it is cloned, or it arrives in a pull request — and a terminal treats some of that text as
instructions rather than as characters. An escape sequence can clear the screen or move the cursor;
a carriage return can overwrite the line just printed. Since elenctic exists to produce a verdict a
reader can act on, text that can rewrite the report is a defect in the product itself, not a
cosmetic one.

So corpus-controlled text passes through :func:`legible` before it is shown. This module has no
elenctic dependencies, so every renderer can reach it — the human one today, and the machine-
readable one that will need exactly the same guarantee.
"""

__all__ = ["legible"]


def legible(text: str) -> str:
    """``text`` with everything a terminal would act on rendered as characters instead.

    Printable characters, spaces and newlines survive; anything else becomes a visible ``\\xNN``
    escape. Escaping rather than dropping keeps the fact that something was there — a reader should
    be able to see that a corpus tried something, not find text quietly missing.

    **Newlines are deliberately kept.** A solver diagnostic is legitimately multi-line, and
    mangling the most common error a user will ever see costs more than the one thing a newline
    still allows: adding a line. It cannot overwrite a line already printed, conceal one, or move
    the cursor, which is what everything else being escaped prevents. A reader who cannot trust
    line *counts* can still trust every line's contents.

    ``str.isprintable`` is the exact predicate wanted here: it is false for every C0 and C1 control
    and for every separator except the space — including the ones that split a line for Python but
    not for clingo or for a diff.
    """
    return "".join(
        character if character.isprintable() or character in " \n" else f"\\x{ord(character):02x}"
        for character in text
    )
