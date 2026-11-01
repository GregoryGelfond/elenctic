"""Text from a program made safe to show on a terminal."""

from typing import Final

_NEWLINE: Final = "\n"


def _is_safe(character: str) -> bool:
    return character.isprintable() or character == _NEWLINE


def _escaped(character: str) -> str:
    return character.encode("unicode_escape").decode("ascii")


def legible(text: str) -> str:
    r"""Show `text` with each character a terminal would act on as a visible escape, like `\x1b`.

    Printable characters and newlines are kept: a newline can add a line but cannot rewrite one
    already written.
    """
    return "".join(character if _is_safe(character) else _escaped(character) for character in text)
