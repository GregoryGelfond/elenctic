"""Read a contract from the `% @tag` comment lines of a program."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce
from itertools import accumulate
from typing import Final, NamedTuple

from elenctic.contract import (
    Asks,
    Assigns,
    Binds,
    Census,
    Claim,
    Contract,
    Costs,
    Entails,
    Reading,
    Satisfiable,
    Solver,
    Witness,
)
from elenctic.determination import Assignment, Mode, Range
from elenctic.literals import AnswerSet, Assumption, Scenario
from elenctic.query import All, Answer
from elenctic.spans import Diagnostic, Position, Severity, Span
from elenctic.syntax import Item, Parsed, read_bindings, read_literals, read_valuations


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
_INTEGER: Final = re.compile(r"-?\d+")
_TOKEN: Final = re.compile(r"(?P<open>\{)|(?P<word>[^\s{=]+|=)")
KNOWN: Final = frozenset(
    {"expect", "count", "model", "optimal", "assign", "cautious", "brave", "cost", "query"}
    | {"elenctic", "note"}
)


class _Scan(NamedTuple):
    """Where a scan of tag text stands: brace depth, and whether inside a string."""

    depth: int = 0
    quoted: bool = False
    escaped: bool = False


def _step(state: _Scan, char: str) -> _Scan:
    """Advance over one character; braces within a string do not count."""
    depth, quoted, escaped = state
    if quoted:
        return _Scan(depth, not (char == '"' and not escaped), char == "\\" and not escaped)
    if char == '"':
        return _Scan(depth, quoted=True)
    return _Scan(depth + (char == "{") - (char == "}"))


def _scan(text: str, state: _Scan = _Scan()) -> _Scan:  # noqa: B008
    return reduce(_step, text, state)


def _block(lines: list[str], index: int, head: re.Match[str], source: str) -> tuple[_Block, int]:
    """Read the tag matched by `head` on `lines[index]` and the comment lines its brace spans."""
    column = len(head["lead"]) + 1
    first = _Piece(
        head["rest"], Position(index + 1, column + len(head["tag"]) + len(head["gap"]) + 1)
    )
    pieces = [first]
    state = _scan(first.text)
    after = index + 1
    while (
        state.depth > 0 and after < len(lines) and (more := _CONTINUATION.fullmatch(lines[after]))
    ):
        piece = _Piece(more["rest"], Position(after + 1, len(more["lead"]) + 1))
        pieces.append(piece)
        state = _scan(piece.text, state)
        after += 1
    return _Block(source, head["tag"], Position(index + 1, column), tuple(pieces)), after


def _blocks(text: str, source: str) -> list[_Block]:
    lines = text.split("\n")
    blocks: list[_Block] = []
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
    states = accumulate(payload[opened:], _step, initial=_Scan())
    return next((opened + i - 1 for i, state in enumerate(states) if i and state.depth == 0), -1)


def _elements(payload: str) -> list[_Element] | None:
    """Split a payload into words and brace groups; `None` if a brace is never closed."""
    found: list[_Element] = []
    at = 0
    while token := _TOKEN.search(payload, at):
        if token["open"] is None:
            found.append(_Element(token["word"], token.start(), braced=False))
            at = token.end()
        elif (closing := _close(payload, token.start())) < 0:
            return None
        else:
            found.append(_Element(payload[token.end() : closing], token.end(), braced=True))
            at = closing + 1
    return found


def _failure(block: _Block, message: str, element: _Element | None = None) -> Diagnostic:
    span = block.whole if element is None else block.span(element.start, element.end)
    return Diagnostic(span, Severity.ERROR, message)


def _ground(block: _Block, element: _Element, *, nonempty: bool = True) -> Parsed[AnswerSet]:
    where = block.span(element.start, element.end)
    items = read_literals(element.text, where) if element.text.strip() else ()
    if isinstance(items, Diagnostic):
        return items
    grounds = [None if item.negated else item.pattern.as_literal() for item in items]
    if None in grounds:
        return _failure(block, "expected ground literals, without `not`", element)
    if nonempty and not grounds:
        return _failure(block, "expected at least one literal", element)
    return frozenset(lit for lit in grounds if lit is not None)


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


def _over(head: list[_Element]) -> tuple[Range, list[_Element]]:
    """Split a leading `optimal` off a payload: the model set the claim is about, and the rest."""
    if head and not head[0].braced and head[0].text == Range.OPTIMAL:
        return Range.OPTIMAL, head[1:]
    return Range.ALL, head


def _count(block: _Block, head: list[_Element]) -> Parsed[Reading]:
    over, rest = _over(head)
    if len(rest) == 1 and not rest[0].braced and rest[0].text.isdecimal():
        return Census(int(rest[0].text), over)
    return _failure(block, "expected a non-negative integer")


def _cost(block: _Block, head: list[_Element]) -> Parsed[Reading]:
    levels = head[0].text.split() if len(head) == 1 and head[0].braced else []
    if levels and all(_INTEGER.fullmatch(level) for level in levels):
        return Costs(tuple(map(int, levels)))
    return _failure(block, "expected `{ c1 c2 ... }`, an integer for each level")


def _litset(
    make: Callable[[AnswerSet, Range], Reading], *, over: Range | None = None
) -> Callable[[_Block, list[_Element]], Parsed[Reading]]:
    """Read `[optimal] { literals }`; with `over` fixed, as for `@optimal`, no `optimal` word."""

    def read(block: _Block, head: list[_Element]) -> Parsed[Reading]:
        chosen, rest = (over, head) if over is not None else _over(head)
        if len(rest) != 1 or not rest[0].braced:
            return _failure(block, "expected `{ literals }`")
        literals = _ground(block, rest[0])
        return literals if isinstance(literals, Diagnostic) else make(literals, chosen)

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


def _valuations(block: _Block, element: _Element) -> Parsed[Assignment]:
    """Read `{ term = integer, ... }`: at least one, and no term given two integers."""
    read = read_valuations(element.text, block.span(element.start, element.end))
    if isinstance(read, Diagnostic):
        return read
    if not read:
        return _failure(block, "expected at least one `term = integer`", element)
    if len({v.variable for v in read}) < len(set(read)):
        return _failure(block, "a term is given two different integers", element)
    return frozenset(read)


def _assign(block: _Block, head: list[_Element]) -> Parsed[Reading]:
    over, rest = _over(head)
    if len(rest) != 1 or not rest[0].braced:
        return _failure(block, "expected `{ term = integer, ... }`")
    assignment = _valuations(block, rest[0])
    return assignment if isinstance(assignment, Diagnostic) else Assigns(assignment, over)


def _witness(over: Range | None = None) -> Callable[[_Block, list[_Element]], Parsed[Reading]]:
    """Read `[optimal] { literals } [where { term = integer, ... }]`, as `@model` or `@optimal`."""

    def read(block: _Block, head: list[_Element]) -> Parsed[Reading]:
        split = _after(block, head, "where", "term = integer, ...")
        if isinstance(split, Diagnostic):
            return split
        assignment = frozenset() if split[1] is None else _valuations(block, split[1])
        if isinstance(assignment, Diagnostic):
            return assignment
        return _litset(lambda lits, chosen: Witness(lits, chosen, assignment), over=over)(
            block, split[0]
        )

    return read


_READERS: Final[dict[str, Callable[[_Block, list[_Element]], Parsed[Reading]]]] = {
    "expect": _expect,
    "count": _count,
    "model": _witness(),
    "optimal": _witness(Range.OPTIMAL),
    "assign": _assign,
    "cost": _cost,
    "cautious": _litset(lambda lits, over: Entails(Mode.CAUTIOUS, lits, over)),
    "brave": _litset(lambda lits, over: Entails(Mode.BRAVE, lits, over)),
    "query": _query,
}


def _split(block: _Block, elements: list[_Element]) -> Parsed[tuple[list[_Element], Scenario]]:
    """Split a tag's elements at `assuming` into its reading and its scenario."""
    split = _after(block, elements, "assuming", "literals")
    if isinstance(split, Diagnostic) or split[1] is None:
        return split if isinstance(split, Diagnostic) else (elements, frozenset())
    scenario = _scenario(block, split[1])
    return scenario if isinstance(scenario, Diagnostic) else (split[0], scenario)


def _after(
    block: _Block, elements: list[_Element], word: str, contents: str
) -> Parsed[tuple[list[_Element], _Element | None]]:
    """Split a trailing `word { ... }` off a tag's elements: what precedes it, and its braces."""
    cut = next((i for i, e in enumerate(elements) if e.text == word and not e.braced), None)
    if cut is None:
        return elements, None
    tail = elements[cut + 1 :]
    if len(tail) != 1 or not tail[0].braced:
        return _failure(block, f"expected `{word} {{ {contents} }}`")
    return elements[:cut], tail[0]


_DIRECTIVES: Final = frozenset({"elenctic", "note"})


def _claim(block: _Block) -> Parsed[Claim] | None:
    if block.tag in _DIRECTIVES:
        return None
    if block.tag not in _READERS:
        return _failure(block, f"`@{block.tag}` is not a tag")
    if (elements := _elements(block.payload)) is None:
        return _failure(block, "a brace is never closed")
    split = _split(block, elements)
    if isinstance(split, Diagnostic):
        return split
    head, scenario = split
    reading = _READERS[block.tag](block, head)
    return reading if isinstance(reading, Diagnostic) else Claim(reading, scenario, block.whole)


def _solver(block: _Block) -> Parsed[Solver]:
    """Read `@elenctic solver NAME`, the one directive."""
    words = [e.text for e in _elements(block.payload) or [] if not e.braced]
    known = ", ".join(Solver)
    match words:
        case ["solver", name] if name in Solver:
            return Solver(name)
        case ["solver", _]:
            return _failure(block, f"unknown solver; known: {known}")
        case ["solver"]:
            return _failure(block, f"`@elenctic solver` needs a solver name; known: {known}")
        case _:
            return _failure(block, "unknown `@elenctic` directive; known: `solver`")


def _declared(blocks: list[_Block]) -> tuple[Solver, list[Diagnostic]]:
    """Find the solver a contract declares (clingo if none) and what is wrong with the declaring."""
    read = [(block, _solver(block)) for block in blocks if block.tag == "elenctic"]
    problems = [r for _, r in read if isinstance(r, Diagnostic)]
    solvers = [(block, r) for block, r in read if isinstance(r, Solver)]
    extra = [_failure(block, "at most one `@elenctic solver`") for block, _ in solvers[1:]]
    return (solvers[0][1] if solvers else Solver.CLINGO), problems + extra


def _expectations(claims: list[Claim], source: str) -> list[Diagnostic]:
    expects = [c for c in claims if isinstance(c.reading, Satisfiable) and not c.scenario]
    start = Span(source, Position(1, 1), Position(1, 1))
    absent = [Diagnostic(start, Severity.ERROR, "missing `@expect`")] if not expects else []
    return absent + [
        Diagnostic(c.span, Severity.ERROR, "more than one `@expect`") for c in expects[1:]
    ]


def _none(reading: Reading) -> bool:
    """Say whether the claim is that there are no answer sets: `@count 0`, of either set."""
    return isinstance(reading, Census) and reading.count == 0


def _expecting(claims: list[Claim], *, satisfiable: bool) -> frozenset[Scenario]:
    """Name the scenarios in which the contract says `@expect sat` (or `unsat`)."""
    return frozenset(c.scenario for c in claims if c.reading == Satisfiable(satisfiable))


def _contradiction(
    claim: Claim, unsat: frozenset[Scenario], sat: frozenset[Scenario]
) -> str | None:
    """Say how a claim contradicts the `@expect` of its own scenario, if it does."""
    reading = claim.reading
    if claim.scenario in unsat and not isinstance(reading, Satisfiable) and not _none(reading):
        return "`@expect unsat` admits no model claim"
    if claim.scenario in sat and _none(reading):
        return "`@count 0` is `@expect unsat`, not `@expect sat`"
    return None


def _exclusions(claims: list[Claim]) -> list[Diagnostic]:
    """Find claims that contradict the `@expect` of their own scenario."""
    unsat, sat = _expecting(claims, satisfiable=False), _expecting(claims, satisfiable=True)
    return [
        Diagnostic(c.span, Severity.ERROR, message)
        for c in claims
        if (message := _contradiction(c, unsat, sat))
    ]


def _nested(claims: list[Claim]) -> list[Diagnostic]:
    """Find an `@count optimal n` above the `@count m` of its scenario: Opt(P) ⊆ AS(P)."""
    counts = {
        (c.scenario, c.reading.over): c.reading.count
        for c in claims
        if isinstance(c.reading, Census)
    }
    return [
        Diagnostic(
            c.span,
            Severity.ERROR,
            f"`@count optimal {c.reading.count}` exceeds `@count {counts[c.scenario, Range.ALL]}`: "
            "the optimal answer sets are among the answer sets",
        )
        for c in claims
        if isinstance(c.reading, Census)
        and c.reading.over is Range.OPTIMAL
        and c.reading.count > counts.get((c.scenario, Range.ALL), c.reading.count)
    ]


def _wellformed(claims: list[Claim], source: str) -> list[Diagnostic]:
    return [*_expectations(claims, source), *_exclusions(claims), *_nested(claims)]


def parse_contract(text: str, source: str = "<string>") -> Contract:
    """Read each tag of `text`: a claim for every one that reads, a diagnostic for the rest."""
    blocks = _blocks(text, source)
    parsed = [(block, _claim(block)) for block in blocks]
    claims = [c for _, c in parsed if isinstance(c, Claim)]
    problems = [c for _, c in parsed if isinstance(c, Diagnostic)]
    solver, misdeclared = _declared(blocks)
    return Contract(tuple(claims), (*problems, *misdeclared, *_wellformed(claims, source)), solver)
