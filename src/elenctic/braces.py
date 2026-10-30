"""Braces in the text of a tag, which open and close a group unless they are in a string."""

from functools import reduce
from itertools import accumulate
from typing import Final, NamedTuple


class Scan(NamedTuple):
    """Where a scan of tag text stands: brace depth, and whether inside a string."""

    depth: int = 0
    quoted: bool = False
    escaped: bool = False


def _step(state: Scan, char: str) -> Scan:
    """Advance over one character; braces within a string do not count."""
    depth, quoted, escaped = state
    if quoted:
        return Scan(depth, not (char == '"' and not escaped), char == "\\" and not escaped)
    if char == '"':
        return Scan(depth, quoted=True)
    return Scan(depth + (char == "{") - (char == "}"))


OUTSIDE: Final = Scan()


def scan(text: str, state: Scan) -> Scan:
    """Advance a scan over `text`."""
    return reduce(_step, text, state)


def closing_brace(payload: str, opened: int) -> int:
    """Return the offset of the brace closing_brace the one at `opened`, or -1."""
    states = accumulate(payload[opened:], _step, initial=OUTSIDE)
    return next((opened + i - 1 for i, state in enumerate(states) if i and state.depth == 0), -1)
