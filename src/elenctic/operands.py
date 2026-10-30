"""The operands of a tag: the words and groups it is read from, and the things they name."""

from elenctic.determination import Assignment, Range
from elenctic.literals import AnswerSet, Assumption, Scenario
from elenctic.spans import Diagnostic, Severity
from elenctic.syntax import Parsed, read_literals, read_valuations
from elenctic.tags import Block, Element


def failure(block: Block, message: str, element: Element | None = None) -> Diagnostic:
    span = block.whole if element is None else block.span(element.start, element.end)
    return Diagnostic(span, Severity.ERROR, message)


def ground(block: Block, element: Element, *, nonempty: bool = True) -> Parsed[AnswerSet]:
    where = block.span(element.start, element.end)
    items = read_literals(element.text, where) if element.text.strip() else ()
    if isinstance(items, Diagnostic):
        return items
    grounds = [None if item.negated else item.pattern.as_literal() for item in items]
    if None in grounds:
        return failure(block, "expected ground literals, without `not`", element)
    if nonempty and not grounds:
        return failure(block, "expected at least one literal", element)
    return frozenset(lit for lit in grounds if lit is not None)


def assumptions(block: Block, element: Element) -> Parsed[Scenario]:
    items = read_literals(element.text, block.span(element.start, element.end))
    if isinstance(items, Diagnostic):
        return items
    assumed = [(item.pattern.as_literal(), not item.negated) for item in items]
    if any(literal is None for literal, _ in assumed):
        return failure(block, "an assumption is a ground literal", element)
    return frozenset(Assumption(literal, holds) for literal, holds in assumed if literal)


def model_set(head: list[Element]) -> tuple[Range, list[Element]]:
    """Split a leading `optimal` off a payload: the model set the claim is about, and the rest."""
    if head and not head[0].braced and head[0].text == Range.OPTIMAL:
        return Range.OPTIMAL, head[1:]
    return Range.ALL, head


def valuations(block: Block, element: Element) -> Parsed[Assignment]:
    """Read `{ term = integer, ... }`: at least one, and no term given two integers."""
    read = read_valuations(element.text, block.span(element.start, element.end))
    if isinstance(read, Diagnostic):
        return read
    if not read:
        return failure(block, "expected at least one `term = integer`", element)
    if len({v.variable for v in read}) < len(set(read)):
        return failure(block, "a term is given two different integers", element)
    return frozenset(read)


def after(
    block: Block, elements: list[Element], word: str, contents: str
) -> Parsed[tuple[list[Element], Element | None]]:
    """Split a trailing `word { ... }` off a tag's elements: what precedes it, and its braces."""
    cut = next((i for i, e in enumerate(elements) if e.text == word and not e.braced), None)
    if cut is None:
        return elements, None
    tail = elements[cut + 1 :]
    if len(tail) != 1 or not tail[0].braced:
        return failure(block, f"expected `{word} {{ {contents} }}`")
    return elements[:cut], tail[0]
