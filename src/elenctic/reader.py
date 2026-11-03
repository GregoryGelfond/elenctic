"""Read a contract from the `% @tag` comment lines of a program."""

from collections.abc import Callable
from typing import Final

from elenctic.contract import Claim, Contract, Reading
from elenctic.determination import Range
from elenctic.directives import declared
from elenctic.literals import Scenario
from elenctic.operands import after, assumptions
from elenctic.queries import query
from elenctic.readings import assign, brave, cautious, cost, count, expect, witness
from elenctic.spans import Diagnostic, Parsed, failure
from elenctic.tags import Block, Element, blocks, elements
from elenctic.wellformed import wellformed

_READERS: Final[dict[str, Callable[[Block, list[Element]], Parsed[Reading]]]] = {
    "expect": expect,
    "count": count,
    "model": witness(),
    "optimal": witness(Range.OPTIMAL),
    "assign": assign,
    "cost": cost,
    "cautious": cautious,
    "brave": brave,
    "query": query,
}


def _split(block: Block, elements: list[Element]) -> Parsed[tuple[list[Element], Scenario]]:
    """Split a tag's elements at `assuming` into its reading and its scenario."""
    split = after(block, elements, "assuming", "literals")
    if isinstance(split, Diagnostic) or split[1] is None:
        return split if isinstance(split, Diagnostic) else (elements, frozenset())
    scenario = assumptions(block, split[1])
    return scenario if isinstance(scenario, Diagnostic) else (split[0], scenario)


_DIRECTIVES: Final = frozenset({"elenctic", "note"})


def _claim(block: Block) -> Parsed[Claim] | None:
    if block.tag in _DIRECTIVES:
        return None
    if block.tag not in _READERS:
        return failure(block.covering(), f"`@{block.tag}` is not a tag")
    if (words := elements(block.payload)) is None:
        return failure(block.covering(), "a brace is never closed")
    split = _split(block, words)
    if isinstance(split, Diagnostic):
        return split
    head, scenario = split
    reading = _READERS[block.tag](block, head)
    return reading if isinstance(reading, Diagnostic) else Claim(reading, scenario, block.whole)


def _claims(each: list[Block]) -> tuple[list[Claim], list[Diagnostic]]:
    """Read each block: the claims that read, and the diagnostics of those that do not."""
    parsed = [_claim(block) for block in each]
    return (
        [c for c in parsed if isinstance(c, Claim)],
        [c for c in parsed if isinstance(c, Diagnostic)],
    )


def parse_contract(text: str, source: str = "<string>") -> Contract:
    """Read each tag of `text`: a claim for every one that reads, a diagnostic for the rest."""
    each = blocks(text, source)
    claims, problems = _claims(each)
    solver, misdeclared = declared(each)
    return Contract(tuple(claims), (*problems, *misdeclared, *wellformed(claims, source)), solver)
