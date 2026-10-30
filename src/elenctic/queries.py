"""The query tag: a question put to the answer sets, with bindings if it has variables."""

from typing import Final

from elenctic.contract import Asks, Binds, Reading
from elenctic.operands import failure
from elenctic.query import All, Answer
from elenctic.rows import read_bindings
from elenctic.spans import Diagnostic, Parsed
from elenctic.syntax import Item, positive, read_literals
from elenctic.tags import Block, Element


def _answer(block: Block, word: Element) -> Parsed[Answer]:
    try:
        return Answer(word.text)
    except ValueError:
        return failure(block, "expected `yes`, `no` or `unknown`", word)


_ASKS: Final = [False, True]


_BINDS: Final = [False, True, False, True]


def query(block: Block, head: list[Element]) -> Parsed[Reading]:
    shape = [e.braced for e in head]
    if shape not in (_ASKS, _BINDS):
        return failure(block, "expected `answer { query }`, or `answer { q(X) } = { bindings }`")
    answer = _answer(block, head[0])
    if isinstance(answer, Diagnostic):
        return answer
    where = block.span(head[1].start, head[1].end)
    items = read_literals(head[1].text, where)
    if isinstance(items, Diagnostic):
        return items
    return (
        _asks(block, answer, items, head[1])
        if shape == _ASKS
        else _binds(block, answer, items, head)
    )


def _asks(
    block: Block, answer: Answer, items: tuple[Item, ...], element: Element
) -> Parsed[Reading]:
    grounds = positive(items)
    if not grounds:
        return failure(
            block, "a query with variables states its bindings: `{ q(X) } = { ... }`", element
        )
    return Asks(answer, All(tuple(grounds)))


def _binds(
    block: Block, answer: Answer, items: tuple[Item, ...], head: list[Element]
) -> Parsed[Reading]:
    if head[2].text != "=" or len(items) != 1 or items[0].negated:
        return failure(block, "expected one positive pattern before `=`", head[1])
    pattern = items[0].pattern
    if not pattern.variables:
        return failure(block, "a pattern with no variables is a ground query", head[1])
    found = read_bindings(
        head[3].text, len(pattern.variables), block.span(head[3].start, head[3].end)
    )
    return found if isinstance(found, Diagnostic) else Binds(answer, pattern, frozenset(found))
