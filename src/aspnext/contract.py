"""The contract: claims about a program, written as `% @tag` comment lines inside it."""

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from clingo import Symbol

from aspnext.determination import Mode
from aspnext.literals import AnswerSet, Assumption, Literal, Pattern, Scenario
from aspnext.query import All, Answer
from aspnext.spans import Diagnostic, Position, Severity, Span
from aspnext.syntax import Item, Parsed, read_bindings, read_literals


@dataclass(frozen=True, slots=True)
class Satisfiable:
    """`@expect sat | unsat`: whether the program has an answer set."""

    expected: bool


@dataclass(frozen=True, slots=True)
class Census:
    """`@count n`: exactly `n` distinct shown answer sets."""

    count: int


@dataclass(frozen=True, slots=True)
class Witness:
    """`@model { L }`: some answer set shows exactly `L`."""

    literals: AnswerSet


@dataclass(frozen=True, slots=True)
class Entails:
    """`@cautious { L }` / `@brave { L }`: `L` is within the cautious / brave consequences."""

    mode: Mode
    literals: AnswerSet


@dataclass(frozen=True, slots=True)
class Asks:
    """`@query A { L, ... }`: the conjunction of ground literals has answer `A`."""

    answer: Answer
    query: All


@dataclass(frozen=True, slots=True)
class Binds:
    """`@query A { q(X, ...) } = { B }`: the bindings giving answer `A` are exactly `B`."""

    answer: Answer
    pattern: Pattern
    bindings: frozenset[tuple[Symbol, ...]]


type Reading = Satisfiable | Census | Witness | Entails | Asks | Binds


@dataclass(frozen=True, slots=True)
class Claim:
    """A reading to hold under a scenario, and where it was written."""

    reading: Reading
    scenario: Scenario
    span: Span


@dataclass(frozen=True, slots=True)
class Contract:
    claims: tuple[Claim, ...]
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class _Piece:
    text: str
    start: Position


@dataclass(frozen=True, slots=True)
class _Block:
    """One tag with its payload, which may have been continued over several comment lines."""

    source: str
    tag: str
    at: Position
    pieces: tuple[_Piece, ...]

    @property
    def payload(self) -> str:
        return " ".join(piece.text for piece in self.pieces)

    def position(self, offset: int) -> Position:
        """Map an offset into `payload` back to a position in the source."""
        starts = [0]
        for piece in self.pieces:
            starts.append(starts[-1] + len(piece.text) + 1)
        index = max(i for i, start in enumerate(starts[:-1]) if start <= offset)
        piece = self.pieces[index]
        return Position(piece.start.line, piece.start.column + offset - starts[index])

    def span(self, start: int, end: int) -> Span:
        return Span(self.source, self.position(start), self.position(end))

    @property
    def whole(self) -> Span:
        last = self.pieces[-1]
        return Span(
            self.source, self.at, Position(last.start.line, last.start.column + len(last.text))
        )


_TAG: Final = re.compile(r"(?P<lead>\s*%\s*)@(?P<tag>\w+)\b(?P<rest>.*)")
_CONTINUATION: Final = re.compile(r"(?P<lead>\s*%\s*)(?P<rest>.*)")
_WORD: Final = re.compile(r"[^\s{=]+")
SUPPORTED: Final = frozenset({"expect", "count", "model", "cautious", "brave", "query", "note"})
KNOWN: Final = SUPPORTED | {"optimal", "cost", "assign", "elenctic"}


def _scan(text: str, depth: int, *, quoted: bool) -> tuple[int, bool]:
    """Carry brace depth and string state across `text`; braces in strings do not count."""
    escaped = False
    for char in text:
        if quoted:
            quoted, escaped = not (char == '"' and not escaped), char == "\\" and not escaped
        elif char == '"':
            quoted = True
        else:
            depth += (char == "{") - (char == "}")
    return depth, quoted


def _block(lines: list[str], index: int, source: str) -> tuple[_Block, int]:
    """Read the tag on `lines[index]` and any comment lines its open brace continues over."""
    head = _TAG.fullmatch(lines[index])
    assert head is not None  # noqa: S101
    column = len(head["lead"]) + 1
    first = _Piece(head["rest"].strip(), Position(index + 1, column + len(head["tag"]) + 1))
    pieces = [first]
    depth, quoted = _scan(first.text, 0, quoted=False)
    after = index + 1
    while depth > 0 and after < len(lines) and (more := _CONTINUATION.fullmatch(lines[after])):
        piece = _Piece(more["rest"].strip(), Position(after + 1, len(more["lead"]) + 1))
        pieces.append(piece)
        depth, quoted = _scan(piece.text, depth, quoted=quoted)
        after += 1
    return _Block(source, head["tag"], Position(index + 1, column), tuple(pieces)), after


def _blocks(text: str, source: str) -> list[_Block]:
    lines = text.split("\n")
    blocks: list[_Block] = []
    index = 0
    while index < len(lines):
        if _TAG.fullmatch(lines[index]):
            block, index = _block(lines, index, source)
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
class _Element:
    """A word, or a brace group without its braces, of a payload."""

    text: str
    start: int
    braced: bool

    @property
    def end(self) -> int:
        return self.start + len(self.text)


def _close(payload: str, opened: int) -> int:
    """Return the offset of the brace closing the one at `opened`, or -1."""
    depth = 0
    quoted = False
    for offset in range(opened, len(payload)):
        depth, quoted = _scan(payload[offset], depth, quoted=quoted)
        if depth == 0 and not quoted:
            return offset
    return -1


def _elements(payload: str) -> list[_Element] | None:
    """Split a payload into words and brace groups; `None` if a brace is never closed."""
    found: list[_Element] = []
    at = 0
    while at < len(payload):
        char = payload[at]
        if char.isspace():
            at += 1
        elif char == "{":
            closing = _close(payload, at)
            if closing < 0:
                return None
            found.append(_Element(payload[at + 1 : closing], at + 1, braced=True))
            at = closing + 1
        else:
            word = _WORD.match(payload, at) or re.compile("=").match(payload, at)
            assert word is not None  # noqa: S101
            found.append(_Element(word[0], at, braced=False))
            at = word.end()
    return found


def _failure(block: _Block, message: str, element: _Element | None = None) -> Diagnostic:
    span = block.whole if element is None else block.span(element.start, element.end)
    return Diagnostic(span, Severity.ERROR, message)


def _ground(block: _Block, element: _Element, *, nonempty: bool = True) -> Parsed[AnswerSet]:
    where = block.span(element.start, element.end)
    items = read_literals(element.text, where) if element.text.strip() else ()
    if isinstance(items, Diagnostic):
        return items
    literals = [item.pattern.as_literal() for item in items if not item.negated]
    if None in literals or len(literals) != len(items):
        return _failure(block, "expected ground literals, without `not`", element)
    if nonempty and not literals:
        return _failure(block, "expected at least one literal", element)
    return frozenset(lit for lit in literals if lit is not None)


def _scenario(block: _Block, element: _Element) -> Parsed[Scenario]:
    items = read_literals(element.text, block.span(element.start, element.end))
    if isinstance(items, Diagnostic):
        return items
    assumed = [(item.pattern.as_literal(), not item.negated) for item in items]
    if any(literal is None for literal, _ in assumed):
        return _failure(block, "an assumption is a ground literal", element)
    return frozenset(Assumption(literal, holds) for literal, holds in assumed if literal)


def _answer(block: _Block, word: _Element) -> Parsed[Answer]:
    try:
        return Answer(word.text)
    except ValueError:
        return _failure(block, "expected `yes`, `no` or `unknown`", word)


def _expect(block: _Block, head: list[_Element]) -> Parsed[Reading]:
    match [e.text for e in head if not e.braced]:
        case ["sat"] if len(head) == 1:
            return Satisfiable(expected=True)
        case ["unsat"] if len(head) == 1:
            return Satisfiable(expected=False)
        case _:
            return _failure(block, "expected `sat` or `unsat`")


def _count(block: _Block, head: list[_Element]) -> Parsed[Reading]:
    if len(head) == 1 and not head[0].braced and head[0].text.isdecimal():
        return Census(int(head[0].text))
    return _failure(block, "expected a non-negative integer")


def _litset(
    make: Callable[[AnswerSet], Reading],
) -> Callable[[_Block, list[_Element]], Parsed[Reading]]:
    def read(block: _Block, head: list[_Element]) -> Parsed[Reading]:
        if len(head) != 1 or not head[0].braced:
            return _failure(block, "expected `{ literals }`")
        literals = _ground(block, head[0])
        return literals if isinstance(literals, Diagnostic) else make(literals)

    return read


def _query(block: _Block, head: list[_Element]) -> Parsed[Reading]:
    shape = [e.braced for e in head]
    if shape not in ([False, True], [False, True, False, True]):
        return _failure(block, "expected `answer { query }`, or `answer { q(X) } = { bindings }`")
    answer = _answer(block, head[0])
    if isinstance(answer, Diagnostic):
        return answer
    where = block.span(head[1].start, head[1].end)
    items = read_literals(head[1].text, where)
    if isinstance(items, Diagnostic):
        return items
    if len(head) == len(shape) == 2:  # noqa: PLR2004
        return _asks(block, answer, items, head[1])
    return _binds(block, answer, items, head)


def _asks(
    block: _Block, answer: Answer, items: tuple[Item, ...], element: _Element
) -> Parsed[Reading]:
    literals = [item.pattern.as_literal() for item in items if not item.negated]
    if not items or None in literals or len(literals) != len(items):
        return _failure(
            block, "a query with variables states its bindings: `{ q(X) } = { ... }`", element
        )
    return Asks(answer, All(tuple(lit for lit in literals if lit)))


def _binds(
    block: _Block, answer: Answer, items: tuple[Item, ...], head: list[_Element]
) -> Parsed[Reading]:
    if head[2].text != "=" or len(items) != 1 or items[0].negated:
        return _failure(block, "expected one positive pattern before `=`", head[1])
    pattern = items[0].pattern
    if not pattern.variables:
        return _failure(block, "a pattern with no variables is a ground query", head[1])
    found = read_bindings(
        head[3].text, len(pattern.variables), block.span(head[3].start, head[3].end)
    )
    return found if isinstance(found, Diagnostic) else Binds(answer, pattern, frozenset(found))


_READERS: Final[dict[str, Callable[[_Block, list[_Element]], Parsed[Reading]]]] = {
    "expect": _expect,
    "count": _count,
    "model": _litset(Witness),
    "cautious": _litset(lambda lits: Entails(Mode.CAUTIOUS, lits)),
    "brave": _litset(lambda lits: Entails(Mode.BRAVE, lits)),
    "query": _query,
}


def _unreadable(block: _Block) -> Diagnostic | None:
    if block.tag in SUPPORTED:
        return None
    return _failure(
        block, f"`@{block.tag}` is " + ("not supported yet" if block.tag in KNOWN else "not a tag")
    )


def _split(block: _Block, elements: list[_Element]) -> Parsed[tuple[list[_Element], Scenario]]:
    """Split a tag's elements at `assuming` into its reading and its scenario."""
    cut = next((i for i, e in enumerate(elements) if e.text == "assuming" and not e.braced), None)
    if cut is None:
        return elements, frozenset()
    tail = elements[cut + 1 :]
    if len(tail) != 1 or not tail[0].braced:
        return _failure(block, "expected `assuming { literals }`")
    scenario = _scenario(block, tail[0])
    return scenario if isinstance(scenario, Diagnostic) else (elements[:cut], scenario)


def _claim(block: _Block) -> Parsed[Claim] | None:
    if block.tag == "note":
        return None
    if (unreadable := _unreadable(block)) is not None:
        return unreadable
    if (elements := _elements(block.payload)) is None:
        return _failure(block, "a brace is never closed")
    split = _split(block, elements)
    if isinstance(split, Diagnostic):
        return split
    head, scenario = split
    reading = _READERS[block.tag](block, head)
    return reading if isinstance(reading, Diagnostic) else Claim(reading, scenario, block.whole)


def _expectations(claims: list[Claim], source: str) -> list[Diagnostic]:
    expects = [c for c in claims if isinstance(c.reading, Satisfiable) and not c.scenario]
    start = Span(source, Position(1, 1), Position(1, 1))
    absent = [Diagnostic(start, Severity.ERROR, "missing `@expect`")] if not expects else []
    return absent + [
        Diagnostic(c.span, Severity.ERROR, "more than one `@expect`") for c in expects[1:]
    ]


def _exclusions(claims: list[Claim]) -> list[Diagnostic]:
    """Find claims that contradict the `@expect` of their own scenario."""
    expected = {(c.scenario, c.reading) for c in claims if isinstance(c.reading, Satisfiable)}
    unsat = {scenario for scenario, reading in expected if reading == Satisfiable(expected=False)}
    sat = {scenario for scenario, reading in expected if reading == Satisfiable(expected=True)}
    clash = [
        Diagnostic(c.span, Severity.ERROR, "`@expect unsat` admits no model claim")
        for c in claims
        if c.scenario in unsat and not isinstance(c.reading, Satisfiable) and c.reading != Census(0)
    ]
    empty = [
        Diagnostic(c.span, Severity.ERROR, "`@count 0` is `@expect unsat`, not `@expect sat`")
        for c in claims
        if c.scenario in sat and c.reading == Census(0)
    ]
    return clash + empty


def _wellformed(claims: list[Claim], source: str) -> list[Diagnostic]:
    return [*_expectations(claims, source), *_exclusions(claims)]


def parse_contract(text: str, source: str = "<string>") -> Contract:
    """Read each tag of `text`: a claim for every one that reads, a diagnostic for the rest."""
    parsed = [(block, _claim(block)) for block in _blocks(text, source)]
    claims = [c for _, c in parsed if isinstance(c, Claim)]
    problems = [c for _, c in parsed if isinstance(c, Diagnostic)]
    return Contract(tuple(claims), (*problems, *_wellformed(claims, source)))


def braces(literals: Iterable[Literal]) -> str:
    """Write literals as the `{ ... }` the contract syntax uses, in a fixed order."""
    return "{ " + ", ".join(map(str, sorted(literals))) + " }"


def _bindings(pattern: Pattern, found: frozenset[tuple[Symbol, ...]]) -> str:
    rows = sorted(",".join(map(str, row)) for row in found)
    return (
        "{ " + ", ".join(rows if len(pattern.variables) == 1 else [f"({r})" for r in rows]) + " }"
    )


def _reading(reading: Reading) -> str:
    match reading:
        case Satisfiable(expected):
            return f"@expect {'sat' if expected else 'unsat'}"
        case Census(count):
            return f"@count {count}"
        case Witness(literals):
            return f"@model {braces(literals)}"
        case Entails(mode, literals):
            return f"@{mode} {braces(literals)}"
        case Asks(answer, All(parts)):
            return f"@query {answer} {braces(p for p in parts if isinstance(p, Literal))}"
        case Binds(answer, pattern, found):
            return f"@query {answer} {{ {pattern} }} = {_bindings(pattern, found)}"


def render(claim: Claim) -> str:
    """Write a claim as the tag line that reads back to it."""
    assumed = sorted(claim.scenario, key=lambda a: (a.literal, a.holds))
    assuming = ", ".join(("" if a.holds else "not ") + str(a.literal) for a in assumed)
    return _reading(claim.reading) + (f" assuming {{ {assuming} }}" if assumed else "")
