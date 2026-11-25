"""The query tag: a question put to the answer sets, with bindings if it has variables."""

import re
from typing import Final

from elenctic.contract import Asks, Binds, Reading
from elenctic.determination import Range
from elenctic.literals import Literal
from elenctic.operands import pointing, read_range, shown
from elenctic.patterns import Pattern
from elenctic.query import All, Answer, Not, unbound_of, variables_of
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


def _stopped(rest: list[Element]) -> list[Element]:
    """Drop the full stop that may end a query, as `ask` reads one: after its closing brace."""
    match rest:
        case [answer, braced, stop] if braced.braced and not stop.braced and stop.text == ".":
            return [answer, braced]
        case _:
            return rest


_SHAPES: Final = "expected `ANSWER { query }` or `ANSWER { query } = { bindings }`"


def query(block: Block, head: list[Element]) -> Parsed[Reading]:
    over, rest = read_range(head)
    rest = _stopped(rest)
    shape = [e.braced for e in rest]
    if shape not in (_ASKS, _BINDS):
        return failure(pointing(block, rest), _SHAPES, label=_SHAPES)
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


def _anonymous(where: Span) -> Diagnostic:
    return failure(
        where,
        "anonymous variable in a query",
        label="`_` has no binding to state",
        help=("name the variable",),
    )


def _open(items: tuple[Item, ...], where: Span) -> Parsed[Pattern | All]:
    """Take parts with variables as the query they are: one pattern alone, else their conjunction.

    `_` names no binding, and a variable only under `not` is bound by no part: both are refused.
    """
    if any(item.pattern.anonymous for item in items):
        return _anonymous(where)
    parts = tuple(_part(item) for item in items)
    query = All(parts)
    unbound = unbound_of(query)
    if unbound:
        return failure(
            where,
            f"variable `{unbound[0].name}` occurs only under `not`",
            label="no part without `not` binds it",
            help=(f"add a part that binds `{unbound[0].name}`, such as a domain atom",),
        )
    match parts:
        case (Pattern() as alone,):
            return alone
        case _:
            return query


_STRING: Final = re.compile(r'"(?:[^"\\]|\\.)*(?:"|\Z)', re.DOTALL)
"""A string, which may hold `;` and parentheses; one left open runs to the end of the text."""


def _separator(text: str) -> int | None:
    """Find the first `;` between the literals of `text`: outside strings and parentheses."""
    bare = _STRING.sub(lambda found: " " * len(found.group()), text)
    depth = 0
    for at, character in enumerate(bare):
        depth += {"(": 1, ")": -1}.get(character, 0)
        if character == ";" and depth == 0:
            return at
    return None


def _items(text: str, where: Span) -> Parsed[tuple[Item, ...]]:
    """Read the parts of a query, literals with or without `not`, which only `,` separates.

    clingo reads `;` in a body as `,`, where Prolog reads it as `or`: a query refuses it.
    """
    at = _separator(text)
    if at is None:
        return read_literals(text, where, refused=frozenset({";"}))
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
    where = block.covering(head[1])
    if head[2].text != "=":
        return failure(
            block.covering(head[2]),
            f"expected `=` before the bindings, found `{head[2].text}`",
            label="expected `=`",
        )
    if _grounds(items) is not None:
        return failure(
            where,
            "query with bindings has no variables",
            label="no variables",
            notes=("a query with no variables is a ground query",),
            help=("ask it as `@query yes { … }` without `= { … }`",),
        )
    query = _open(items, where)
    if isinstance(query, Diagnostic):
        return query
    arity = len(variables_of(query))
    found = read_bindings(head[3].text, arity, block.span(head[3].start, head[3].end))
    return found if isinstance(found, Diagnostic) else Binds(answer, query, frozenset(found), over)


def read_query(text: str, source: str) -> Parsed[All | Pattern]:
    """Read a query as `@query` writes it, `{ L, … }` or `{ q(X, …), not r(X) }`, braces optional.

    Its parts are literals or patterns, `not` before any; ground parts are their conjunction, and
    parts with variables ask for their bindings, one pattern alone being that pattern. A full stop
    may end it.
    """
    body, at, where = asked(text, source)
    if not body.strip():
        return _empty(where)
    items = _items(body, at)
    if isinstance(items, Diagnostic):
        return items
    grounds = _grounds(items)
    return All(grounds) if grounds is not None else _open(items, where)
