"""Where things are: positions and spans in a source, and the diagnostics attached to them."""

import re
from bisect import bisect_left
from dataclasses import dataclass
from enum import StrEnum, auto
from functools import lru_cache
from itertools import accumulate
from typing import Final, override


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A point in a source; line and column both count from 1."""

    line: int
    column: int


@dataclass(frozen=True, slots=True)
class Span:
    """The half-open stretch of `source` from `start` to `end`."""

    source: str
    start: Position
    end: Position

    @override
    def __str__(self) -> str:
        end = self.end
        tail = f"{end.column}" if end.line == self.start.line else f"{end.line}:{end.column}"
        return f"{self.source}:{self.start.line}:{self.start.column}-{tail}"

    def shifted(self, origin: Position) -> Span:
        """Place this span, read as relative to `origin`, in the enclosing source."""
        return Span(self.source, _shift(self.start, origin), _shift(self.end, origin))

    @classmethod
    def whole(cls, source: str, text: str) -> Span:
        """Span all of `text`, such as an argument a command was given, to its last line's end."""
        lines = text.split("\n")
        return cls(source, Position(1, 1), Position(len(lines), len(lines[-1]) + 1))


def _shift(position: Position, origin: Position) -> Position:
    return Position(
        origin.line + position.line - 1,
        position.column + (origin.column - 1 if position.line == 1 else 0),
    )


class Severity(StrEnum):
    """How serious a diagnostic is."""

    ERROR = auto()
    WARNING = auto()
    NOTE = auto()
    HELP = auto()


@dataclass(frozen=True, slots=True)
class Child:
    """A note or help attached to a diagnostic."""

    severity: Severity
    message: str


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A message about a span, or about the whole source when `span` is none."""

    span: Span | None
    severity: Severity
    message: str
    label: str = ""
    children: tuple[Child, ...] = ()


type Parsed[T] = T | Diagnostic


def failure(
    where: Span | None,
    message: str,
    *,
    label: str = "",
    notes: tuple[str, ...] = (),
    help: tuple[str, ...] = (),  # noqa: A002
) -> Diagnostic:
    """Say that something at `where` is wrong."""
    children = tuple(Child(Severity.NOTE, note) for note in notes) + tuple(
        Child(Severity.HELP, tip) for tip in help
    )
    return Diagnostic(where, Severity.ERROR, message, label, children)


def note(
    where: Span | None,
    message: str,
    *,
    help: tuple[str, ...] = (),  # noqa: A002
) -> Diagnostic:
    """Say something about `where` that does not fail the run."""
    return Diagnostic(
        where, Severity.NOTE, message, "", tuple(Child(Severity.HELP, tip) for tip in help)
    )


def one_line(text: str) -> str:
    """Put text written over several comment lines on one line, single-spaced."""
    return " ".join(text.split())


def char_column(line: str, byte_column: int) -> int:
    """Map a 1-based UTF-8 byte column to a 1-based Unicode scalar column.

    It is the first character to start at or past the byte, or the end of the line.
    """
    if byte_column <= 1:
        return 1
    starts = _byte_starts(line)
    if starts is None:
        return min(byte_column, len(line) + 1)
    return bisect_left(starts, byte_column - 1) + 1


@lru_cache(maxsize=16)
def _byte_starts(line: str) -> tuple[int, ...] | None:
    """Return the UTF-8 byte offset each character of `line` starts at; `None` when all are ASCII.

    A line is measured once, however many of its columns are mapped.
    """
    if line.isascii():
        return None
    return tuple(accumulate((len(character.encode()) for character in line[:-1]), initial=0))


@lru_cache(maxsize=16)
def split_lines(text: str) -> tuple[str, ...]:
    """Split a source's text into its lines, line 1 first.

    Each text is split once, however many of its lines are read: reading every rule's line of a
    program stays linear in its length. A line ends at a line feed alone, as clingo counts lines;
    the carriage return of a CRLF ending is left off, as no part of what the line says.
    """
    return tuple(line.removesuffix("\r") for line in text.split("\n"))


def _line_at(text: str, number: int) -> str:
    lines = split_lines(text)
    return lines[number - 1] if 1 <= number <= len(lines) else ""


def in_characters(span: Span, text: str) -> Span:
    """Rewrite a span whose columns count UTF-8 bytes so they count Unicode scalars."""
    start = Position(
        span.start.line, char_column(_line_at(text, span.start.line), span.start.column)
    )
    end = Position(span.end.line, char_column(_line_at(text, span.end.line), span.end.column))
    return Span(span.source, start, end)


_ASCII_MAX = 127


_STRING: Final = re.compile(r'"(?:[^\\"\n]|\\["\\n])*"')
"""A string as clingo's lexer reads one: on one line, escaping only `"`, `\\` and newline.

A `"` that opens no such string is a stray character, and what follows it is code.
"""


@dataclass(frozen=True, slots=True)
class Lexeme:
    """A comment or a string: text from `start` to `end` that clingo's lexer reads as one piece."""

    start: int
    end: int
    string: bool


def _line_end(text: str, index: int) -> int:
    end = text.find("\n", index)
    return len(text) if end < 0 else end


def _comment_end(text: str, start: int) -> int:
    """Return where the comment opening at `start` ends.

    A `%` or `#!` comments out the rest of its line. Block comments nest, and a `%` inside one
    comments out the rest of that line, closers included.
    """
    if not text.startswith("%*", start):
        return _line_end(text, start)
    depth, index, length = 1, start + 2, len(text)
    while index < length:
        if text.startswith("%*", index):
            depth, index = depth + 1, index + 2
        elif text.startswith("*%", index):
            depth, index = depth - 1, index + 2
            if depth == 0:
                return index
        elif text[index] == "%":
            index = _line_end(text, index)
        else:
            index += 1
    return index


_SCRIPT: Final = re.compile(r"#script\s*\(\s*\w+\s*\)")
"""The head of an embedded script, whose code clingo's lexer passes over to the first `#end`."""
_OPENING: Final = re.compile(r'%|"|#!|#script\b')
"""Where a comment, a string or a script may open; nothing else in code begins a lexeme."""

_LEXED: Final = 8
"""How many texts' lexemes are remembered: each text is read in turn by several readers."""


@lru_cache(maxsize=_LEXED)
def lexemes(text: str) -> tuple[Lexeme, ...]:
    """Return the comments, strings and scripts of `text`, in order, as clingo's lexer reads them.

    A script's code, from its head to the first `#end`, clingo's lexer passes over, as a comment.
    """
    found: list[Lexeme] = []
    index = 0
    while (opening := _OPENING.search(text, index)) is not None:
        index = opening.start()
        if text[index] == "%" or text.startswith("#!", index):
            found.append(Lexeme(index, end := _comment_end(text, index), string=False))
        elif (script := _SCRIPT.match(text, index)) is not None:
            closing = text.find("#end", script.end())
            end = len(text) if closing < 0 else closing
            found.append(Lexeme(script.end(), end, string=False))
        elif (string := _STRING.match(text, index)) is not None:
            found.append(Lexeme(index, end := string.end(), string=True))
        else:
            end = index + 1
        index = end
    return tuple(found)


@lru_cache(maxsize=_LEXED)
def in_code(text: str) -> tuple[bool, ...]:
    """Mark each character that sits outside strings and comments."""
    mask = [True] * len(text)
    for lexeme in lexemes(text):
        mask[lexeme.start : lexeme.end] = [False] * (lexeme.end - lexeme.start)
    return tuple(mask)


_ESCAPED: Final = range(0xDC00, 0xDD00)
"""The lone surrogates Python reads a byte that is not UTF-8 in an argument as, from `0x00`."""


def _not_utf8(where: Span, byte: int) -> Diagnostic:
    return failure(
        where,
        f"expected UTF-8, found the byte `0x{byte:02X}`",
        label="not UTF-8",
        help=("clingo reads only UTF-8; write the text in UTF-8",),
    )


def first_nul(text: str, where: Span) -> Diagnostic | None:
    """Refuse a NUL in `text`, written at `where`, which clingo is given as a string a NUL ends.

    Clingo would read the text up to it alone, wherever it stands, even in a string or a comment.
    """
    index = text.find(_NUL)
    if index < 0:
        return None
    line = text.count("\n", 0, index) + 1
    column = index - text.rfind("\n", 0, index)
    at = Span(where.source, Position(line, column), Position(line, column + 1))
    return failure(
        at.shifted(where.start), f"unexpected `{_NUL}`", label="a NUL ends clingo's text"
    )


def first_unlexable(text: str, source: str) -> Diagnostic | None:
    """Return a diagnostic for the first non-ASCII outside a string or comment, or non-UTF-8.

    Clingo reads UTF-8 only: a byte that is not, kept in an argument as a lone surrogate, cannot
    be given it, even in a string. Its lexer accepts only ASCII outside one; with a Python
    logger, a rejected character makes pyclingo abort the process. elenctic refuses the text
    first so that never happens.
    """
    if text.isascii():
        return None
    code = in_code(text)
    line, column = 1, 1
    for index, character in enumerate(text):
        if _ESCAPED.start <= ord(character) < _ESCAPED.stop:
            where = Span(source, Position(line, column), Position(line, column + 1))
            return _not_utf8(where, ord(character) - _ESCAPED.start)
        if code[index] and ord(character) > _ASCII_MAX:
            where = Span(source, Position(line, column), Position(line, column + 1))
            if character == "\ufeff":
                return failure(
                    where,
                    "byte order mark at the start of the file",
                    label="unexpected BOM",
                    help=("save the file as UTF-8 without a BOM",),
                )
            shown = character if character.isprintable() else f"U+{ord(character):04X}"
            return failure(
                where,
                f"expected an ASCII character, found `{shown}`",
                label="outside strings and comments",
                help=("clingo's lexer rejects non-ASCII here; keep it in a string or a comment",),
            )
        if character == "\n":
            line += 1
            column = 1
        else:
            column += 1
    return None


_HEADER: Final = re.compile(
    r"(?P<source>.+?):(?P<line>\d+):(?P<column>\d+)"
    r"(?:-(?P<end_line>\d+):(?P<end_column_far>\d+)|-(?P<end_column>\d+))?"
    r": (?P<severity>error|warning|info|note): (?P<message>.*)"
)
_SEVERITY: Final = {"error": Severity.ERROR, "warning": Severity.WARNING}


def diagnose(
    message: str,
    text: str | None = None,
    ends: Position | None = None,
    *,
    refused: frozenset[str] = frozenset(),
) -> tuple[Diagnostic, ...]:
    """Read clingo's text for a problem as one diagnostic per located line.

    Clingo counts columns in UTF-8 bytes: given the `text` it read, each span is converted to
    Unicode columns; without it, each keeps clingo's columns and source name.
    Continuation lines become `note` children of the header they follow. An empty message yields
    no diagnostic. A syntax error is worded `expected X, found Y`; what it finds at or past `ends`,
    text appended to the one written, is the end of the input. A token in `refused`, which the
    reader turns away though clingo's grammar takes it, is not among the expected.
    """
    if not message.strip():
        return ()
    lines = message.rstrip("\n").split("\n")
    heads = [(i, found) for i, line in enumerate(lines) if (found := _HEADER.fullmatch(line))]
    bounds = [*(i for i, _ in heads), len(lines)]
    found_all = tuple(
        _located(found, lines[i + 1 : end], text, ends, refused)
        for (i, found), end in zip(heads, bounds[1:], strict=True)
    )
    return found_all or (failure(None, message.strip()),)


def _located(
    header: re.Match[str],
    continuation: list[str],
    text: str | None,
    ends: Position | None,
    refused: frozenset[str],
) -> Diagnostic:
    start = Position(int(header["line"]), int(header["column"]))
    end = Position(
        int(header["end_line"] or start.line),
        int(header["end_column_far"] or header["end_column"] or start.column),
    )
    span = Span(header["source"], start, end)
    if text is not None:
        span = in_characters(span, text)
    children = tuple(Child(Severity.NOTE, line) for line in continuation if line.strip())
    return Diagnostic(
        span,
        _SEVERITY.get(header["severity"], Severity.NOTE),
        _worded(header["message"], ended=ends is not None and span.start >= ends, refused=refused),
        children=children,
    )


_SYNTAX: Final = re.compile(
    r"(?:syntax|lexer) error, unexpected (?P<found>.*?)(?:, expecting (?P<expected>.+))?"
)
_NUL: Final = "\x00"


def _worded(message: str, *, ended: bool, refused: frozenset[str]) -> str:
    """Word clingo's `syntax error, unexpected Y, expecting X or Z`: `expected X or Z, found Y`.

    A token in `refused` is not offered: if no other is, the error is `unexpected Y`. Clingo's
    message ends at a NUL, so a character it names as nothing is one.
    """
    if (error := _SYNTAX.fullmatch(message)) is None:
        return message
    found = "end of input" if ended else _token(error["found"] or _NUL)
    offered = _offered(error["expected"] or "", refused)
    if not offered:
        return f"unexpected {found}"
    *others, last = (_token(token) for token in offered)
    expected = f"{', '.join(others)} or {last}" if others else last
    return f"expected {expected}, found {found}"


def _offered(expected: str, refused: frozenset[str]) -> list[str]:
    """Return the tokens clingo's `expecting X or Z` offers, but those in `refused`."""
    return [token for token in expected.split(" or ") if token and token.strip('"') not in refused]


def _token(name: str) -> str:
    """Name a token of clingo's grammar: `<IDENTIFIER>` an identifier, `EOF` the end of input."""
    if name == "EOF":
        return "end of input"
    if name.startswith("<") and name.endswith(">"):
        return name[1:-1].lower()
    return f"`{name.strip('"') or name}`"


def _undecoded(error: UnicodeDecodeError) -> str:
    """Say where the byte that is not UTF-8 stands: its line, its column and its byte, from 1."""
    data = bytes(error.object)
    start = data.rfind(b"\n", 0, error.start) + 1
    column = len(data[start : error.start].decode("utf-8", errors="replace")) + 1
    line = data.count(b"\n", 0, error.start) + 1
    return f"line {line}, column {column} (byte {error.start + 1})"


def unreadable(source: str, error: OSError | UnicodeDecodeError) -> Diagnostic:
    """Say that the file `source` cannot be read, and why."""
    match error:
        case UnicodeDecodeError():
            note = f"not valid UTF-8 at {_undecoded(error)}: {error.reason}"
        case _:
            note = str(error)
    return failure(None, f"cannot read `{source}`", notes=(note,))
