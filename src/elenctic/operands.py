"""The operands of a tag: the words and groups it is read from, and the things they name."""

from elenctic.determination import Assignment, Range
from elenctic.literals import Assumption, Atoms, Scenario
from elenctic.spans import Diagnostic, Parsed, failure
from elenctic.syntax import literals, positive, read_literals, read_valuations
from elenctic.tags import Block, Element


def ground(block: Block, element: Element, *, nonempty: bool = True) -> Parsed[Atoms]:
    where = block.span(element.start, element.end)
    items = read_literals(element.text, where) if element.text.strip() else ()
    if isinstance(items, Diagnostic):
        return items
    grounds = positive(items)
    if grounds is None:
        return failure(block.covering(element), "expected ground literals, without `not`")
    if nonempty and not grounds:
        return failure(block.covering(element), "expected at least one literal")
    return frozenset(grounds)


def assumptions(block: Block, element: Element) -> Parsed[Scenario]:
    items = read_literals(element.text, block.span(element.start, element.end))
    if isinstance(items, Diagnostic):
        return items
    grounds = literals(items)
    if grounds is None:
        return failure(block.covering(element), "an assumption is a ground literal")
    return frozenset(
        Assumption(literal, holds=not item.negated)
        for literal, item in zip(grounds, items, strict=True)
    )


def read_range(head: list[Element]) -> tuple[Range, list[Element]]:
    """Split a leading `optimal` off a payload: the answer sets the claim is about, and the rest."""
    if head and not head[0].braced and head[0].text == Range.OPTIMAL:
        return Range.OPTIMAL, head[1:]
    return Range.ALL, head


def valuations(block: Block, element: Element) -> Parsed[Assignment]:
    """Read `{ term = integer, ... }`: at least one, and no term given two integers."""
    read = read_valuations(element.text, block.span(element.start, element.end))
    if isinstance(read, Diagnostic):
        return read
    if not read:
        return failure(block.covering(element), "expected at least one `term = integer`")
    if len({v.variable for v in read}) < len(set(read)):
        return failure(block.covering(element), "a term is given two different integers")
    return frozenset(read)


def _bare(elements: list[Element], word: str) -> int | None:
    """Find where `word` stands among the elements, outside any braces."""
    return next((i for i, e in enumerate(elements) if e.text == word and not e.braced), None)


def after(
    block: Block, elements: list[Element], word: str, contents: str
) -> Parsed[tuple[list[Element], Element | None]]:
    """Split a trailing `word { ... }` off a tag's elements: what precedes it, and its braces."""
    cut = _bare(elements, word)
    if cut is None:
        return elements, None
    tail = elements[cut + 1 :]
    if len(tail) != 1 or not tail[0].braced:
        return failure(block.covering(), f"expected `{word} {{ {contents} }}`")
    return elements[:cut], tail[0]
