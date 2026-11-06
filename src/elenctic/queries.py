"""The query tag: a question put to the answer sets, with bindings if it has variables."""

from typing import Final

from elenctic.contract import Asks, Binds, Reading
from elenctic.determination import Range
from elenctic.operands import pointing, read_range, shown
from elenctic.query import All, Answer
from elenctic.rows import read_bindings
from elenctic.spans import Diagnostic, Parsed, failure
from elenctic.syntax import Item, literals, read_literals
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
    items = read_literals(rest[1].text, where)
    if isinstance(items, Diagnostic):
        return items
    return (
        _asks(block, answer, items, rest[1], over)
        if shape == _ASKS
        else _binds(block, answer, items, rest, over)
    )


def _asks(
    block: Block, answer: Answer, items: tuple[Item, ...], element: Element, over: Range
) -> Parsed[Reading]:
    where = block.covering(element)
    if any(item.negated for item in items):
        return failure(
            where,
            "query uses `not`",
            label="`not` is not a query atom",
            help=("drop `not`, or state a positive pattern with bindings",),
        )
    grounds = literals(items)
    if grounds is None:
        return failure(
            where,
            "query with variables states no bindings",
            label="has variables",
            help=(f"state its bindings: `{{ {shown(element)} }} = {{ ... }}`",),
        )
    if not grounds:
        return failure(
            where,
            "expected at least one atom, found `{ }`",
            label="empty query",
        )
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
        return failure(
            block.covering(head[1]),
            "anonymous variable in a binding pattern",
            label="`_` has no binding to state",
            help=("name the variable",),
        )
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
