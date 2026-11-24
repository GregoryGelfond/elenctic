"""The query tag: a question put to the answer sets, with bindings if it has variables."""

from enum import StrEnum, auto
from typing import Final

from elenctic.contract import Asks, Binds, Reading
from elenctic.determination import Range
from elenctic.literals import Literal
from elenctic.operands import pointing, read_range, shown
from elenctic.patterns import Pattern
from elenctic.query import All, Answer, Not
from elenctic.rows import read_bindings
from elenctic.spans import Diagnostic, Parsed, Position, Span, failure
from elenctic.syntax import Item, asked, read_literals
from elenctic.tags import Block, Element


def _answer(block: Block, word: Element) -> Parsed[Answer]:
    try:
        return Answer(word.text)
    except ValueError:
        return failure(
            block.covering(word),
            f"expected `yes`, `no`, or `unknown`, found `{word.text}`",
            label="expected `yes`, `no`, or `unknown`",
        )


_ASKS: Final = [False, True]


_BINDS: Final = [False, True, False, True]


def query(block: Block, head: list[Element]) -> Parsed[Reading]:
    over, rest = read_range(head)
    shape = [e.braced for e in rest]
    if shape not in (_ASKS, _BINDS):
        return failure(
            pointing(block, rest),
            "expected `ANSWER { query }` or `ANSWER { q(X) } = { bindings }`",
            label="expected `ANSWER { query }` or `ANSWER { q(X) } = { bindings }`",
        )
    answer = _answer(block, rest[0])
    if isinstance(answer, Diagnostic):
        return answer
    where = block.span(rest[1].start, rest[1].end)
    items = _items(rest[1].text, where)
    if isinstance(items, Diagnostic):
        return items
    return (
        _asks(block, answer, items, rest[1], over)
        if shape == _ASKS
        else _binds(block, answer, items, rest, over)
    )


class _Refusal(StrEnum):
    """A query `@query` and `ask` both refuse."""

    ANONYMOUS = auto()
    SEVERAL = auto()


def _refused(where: Span, refusal: _Refusal) -> Diagnostic:
    """Refuse a query: an anonymous variable, or more than one pattern with variables."""
    match refusal:
        case _Refusal.ANONYMOUS:
            return failure(
                where,
                "anonymous variable in a binding pattern",
                label="`_` has no binding to state",
                help=("name the variable",),
            )
        case _Refusal.SEVERAL:
            return failure(
                where,
                "query with variables has one pattern",
                label="more than one literal",
                help=("ask each pattern on its own",),
            )


def _separator(text: str) -> int | None:
    """Find the first `;` between the literals of `text`: outside strings and parentheses."""
    depth, quoted, escaped = 0, False, False
    for at, character in enumerate(text):
        if quoted:
            quoted = escaped or character != '"'
            escaped = not escaped and character == "\\"
        elif character == '"':
            quoted = True
        elif character in "()":
            depth += 1 if character == "(" else -1
        elif character == ";" and depth == 0:
            return at
    return None


def _items(text: str, where: Span) -> Parsed[tuple[Item, ...]]:
    """Read the parts of a query, literals with or without `not`, which only `,` separates.

    clingo reads `;` in a body as `,`, where Prolog reads it as `or`: a query refuses it.
    """
    at = _separator(text)
    if at is None:
        return read_literals(text, where)
    before = text[:at]
    line = where.start.line + before.count("\n")
    column = (at - before.rfind("\n")) if "\n" in before else where.start.column + at
    stands = Span(where.source, Position(line, column), Position(line, column + 1))
    return failure(
        stands,
        "query uses a semicolon",
        label="not a separator in a query",
        help=("separate the literals with `,`",),
    )


def _part(item: Item) -> Literal | Pattern | Not:
    """Take one item of a query as the part it is: ground, a literal; `not` before it, negated."""
    literal = item.pattern.as_literal()
    part = item.pattern if literal is None else literal
    return Not(part) if item.negated else part


def _grounds(items: tuple[Item, ...]) -> tuple[Literal | Not, ...] | None:
    """Return the parts of a query with no variables, or `None` if some part has them."""
    if any(item.pattern.as_literal() is None for item in items):
        return None
    return tuple(part for item in items if not isinstance(part := _part(item), Pattern))


def _empty(where: Span) -> Diagnostic:
    return failure(where, "expected at least one atom, found `{ }`", label="empty query")


def _asks(
    block: Block, answer: Answer, items: tuple[Item, ...], element: Element, over: Range
) -> Parsed[Reading]:
    where = block.covering(element)
    grounds = _grounds(items)
    if grounds is None:
        return failure(
            where,
            "query with variables states no bindings",
            label="has variables",
            help=(f"state its bindings: `{{ {shown(element)} }} = {{ ... }}`",),
        )
    if not grounds:
        return _empty(where)
    return Asks(answer, All(tuple(grounds)), over)


def _binds(
    block: Block, answer: Answer, items: tuple[Item, ...], head: list[Element], over: Range
) -> Parsed[Reading]:
    if head[2].text != "=" or len(items) != 1 or items[0].negated:
        return failure(
            block.covering(head[1]),
            f"expected one positive pattern before `=`, found `{shown(head[1:2])}`",
            label="expected one positive pattern before `=`",
        )
    pattern = items[0].pattern
    if pattern.anonymous:
        return _refused(block.covering(head[1]), _Refusal.ANONYMOUS)
    if not pattern.variables:
        return failure(
            block.covering(head[1]),
            "binding pattern has no variables",
            label="no variables",
            notes=("a pattern with no variables is a ground query",),
            help=("ask it as `@query yes { … }` without `= { … }`",),
        )
    found = read_bindings(
        head[3].text, len(pattern.variables), block.span(head[3].start, head[3].end)
    )
    return (
        found if isinstance(found, Diagnostic) else Binds(answer, pattern, frozenset(found), over)
    )


def read_query(text: str, source: str) -> Parsed[All | Pattern]:
    """Read a query as `@query` writes it, `{ L, … }` or `{ q(X, …) }`, the braces optional.

    Ground parts, literals with or without `not`, are their conjunction; one pattern with
    variables asks for its bindings. A full stop may end it.
    """
    body, at, where = asked(text, source)
    if not body.strip():
        return _empty(where)
    items = _items(body, at)
    if isinstance(items, Diagnostic):
        return items
    grounds = _grounds(items)
    if grounds is not None:
        return All(grounds)
    if len(items) != 1 or items[0].negated:
        return _refused(where, _Refusal.SEVERAL)
    pattern = items[0].pattern
    return _refused(where, _Refusal.ANONYMOUS) if pattern.anonymous else pattern
