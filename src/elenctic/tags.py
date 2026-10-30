"""The tags of a program's comments: where each begins and ends, and the words and groups in it."""

import re
from dataclasses import dataclass
from typing import Final

from elenctic.braces import OUTSIDE, closing_brace, scan
from elenctic.spans import Position, Span


@dataclass(frozen=True, slots=True)
class Piece:
    text: str
    start: Position


@dataclass(frozen=True, slots=True)
class Block:
    """One tag with its payload, which may have been continued over several comment lines."""

    source: str
    tag: str
    at: Position
    pieces: tuple[Piece, ...]

    @property
    def payload(self) -> str:
        """The tag's text, laid out as in the source: each line indented to its own column."""
        return "\n".join(" " * (piece.start.column - 1) + piece.text for piece in self.pieces)

    def position(self, offset: int) -> Position:
        """Map an offset into `payload` back to a position in the source."""
        before = self.payload[:offset]
        column = offset - (before.rfind("\n") + 1) + 1
        return Position(self.pieces[0].start.line + before.count("\n"), column)

    def span(self, start: int, end: int) -> Span:
        return Span(self.source, self.position(start), self.position(end))

    @property
    def whole(self) -> Span:
        last = self.pieces[-1]
        return Span(
            self.source, self.at, Position(last.start.line, last.start.column + len(last.text))
        )


_TAG: Final = re.compile(r"(?P<lead>\s*%\s*)@(?P<tag>\w+)\b(?P<gap>\s*)(?P<rest>.*?)\s*")


_CONTINUATION: Final = re.compile(r"(?P<lead>\s*%\s*)(?P<rest>.*?)\s*")


_TOKEN: Final = re.compile(r"(?P<open>\{)|(?P<word>[^\s{=]+|=)")


KNOWN: Final = frozenset(
    {"expect", "count", "model", "optimal", "assign", "cautious", "brave", "cost", "query"}
    | {"elenctic", "note"}
)


def _block(lines: list[str], index: int, head: re.Match[str], source: str) -> tuple[Block, int]:
    """Read the tag matched by `head` on `lines[index]` and the comment lines its brace spans."""
    column = len(head["lead"]) + 1
    first = Piece(
        head["rest"], Position(index + 1, column + len(head["tag"]) + len(head["gap"]) + 1)
    )
    pieces = [first]
    state = scan(first.text, OUTSIDE)
    after = index + 1
    while (
        state.depth > 0 and after < len(lines) and (more := _CONTINUATION.fullmatch(lines[after]))
    ):
        piece = Piece(more["rest"], Position(after + 1, len(more["lead"]) + 1))
        pieces.append(piece)
        state = scan(piece.text, state)
        after += 1
    return Block(source, head["tag"], Position(index + 1, column), tuple(pieces)), after


def blocks(text: str, source: str) -> list[Block]:
    lines = text.split("\n")
    blocks: list[Block] = []
    index = 0
    while index < len(lines):
        if head := _TAG.fullmatch(lines[index]):
            block, index = _block(lines, index, head, source)
            blocks.append(block)
        else:
            index += 1
    return blocks


def is_case(text: str) -> bool:
    """Say whether `text` is a case (some contract tag) rather than a library."""
    return any(
        (found := _TAG.fullmatch(line)) and found["tag"] in KNOWN for line in text.split("\n")
    )


@dataclass(frozen=True, slots=True)
class Element:
    """A word, or a brace group without its braces, of a payload."""

    text: str
    start: int
    braced: bool

    @property
    def end(self) -> int:
        return self.start + len(self.text)


def elements(payload: str) -> list[Element] | None:
    """Split a payload into words and brace groups; `None` if a brace is never closed."""
    found: list[Element] = []
    at = 0
    while token := _TOKEN.search(payload, at):
        if token["open"] is None:
            found.append(Element(token["word"], token.start(), braced=False))
            at = token.end()
        elif (end := closing_brace(payload, token.start())) < 0:
            return None
        else:
            found.append(Element(payload[token.end() : end], token.end(), braced=True))
            at = end + 1
    return found
