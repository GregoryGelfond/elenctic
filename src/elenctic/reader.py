"""Read a contract from the `% @tag` comment lines of a program."""

from collections.abc import Callable
from typing import Final

from elenctic.contract import Claim, Contract, Reading, Solver
from elenctic.determination import Range
from elenctic.literals import Scenario
from elenctic.operands import after, assumptions, failure
from elenctic.queries import query
from elenctic.readings import assign, brave, cautious, cost, count, expect, witness
from elenctic.spans import Diagnostic
from elenctic.syntax import Parsed
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
        return failure(block, f"`@{block.tag}` is not a tag")
    if (words := elements(block.payload)) is None:
        return failure(block, "a brace is never closed")
    split = _split(block, words)
    if isinstance(split, Diagnostic):
        return split
    head, scenario = split
    reading = _READERS[block.tag](block, head)
    return reading if isinstance(reading, Diagnostic) else Claim(reading, scenario, block.whole)


def _solver(block: Block) -> Parsed[Solver]:
    """Read `@elenctic solver NAME`, the one directive."""
    words = [e.text for e in elements(block.payload) or [] if not e.braced]
    known = ", ".join(Solver)
    match words:
        case ["solver", name] if name in Solver:
            return Solver(name)
        case ["solver", _]:
            return failure(block, f"unknown solver; known: {known}")
        case ["solver"]:
            return failure(block, f"`@elenctic solver` needs a solver name; known: {known}")
        case _:
            return failure(block, "unknown `@elenctic` directive; known: `solver`")


def _declared(blocks: list[Block]) -> tuple[Solver, list[Diagnostic]]:
    """Find the solver a contract declares (clingo if none) and what is wrong with the declaring."""
    read = [(block, _solver(block)) for block in blocks if block.tag == "elenctic"]
    problems = [r for _, r in read if isinstance(r, Diagnostic)]
    solvers = [(block, r) for block, r in read if isinstance(r, Solver)]
    extra = [failure(block, "at most one `@elenctic solver`") for block, _ in solvers[1:]]
    return (solvers[0][1] if solvers else Solver.CLINGO), problems + extra


def parse_contract(text: str, source: str = "<string>") -> Contract:
    """Read each tag of `text`: a claim for every one that reads, a diagnostic for the rest."""
    each = blocks(text, source)
    parsed = [(block, _claim(block)) for block in each]
    claims = [c for _, c in parsed if isinstance(c, Claim)]
    problems = [c for _, c in parsed if isinstance(c, Diagnostic)]
    solver, misdeclared = _declared(each)
    return Contract(tuple(claims), (*problems, *misdeclared, *wellformed(claims, source)), solver)
