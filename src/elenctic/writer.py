"""Write a claim as the tag line that reads back to it."""

from collections.abc import Iterable

from elenctic.contract import (
    Asks,
    Binds,
    Census,
    Claim,
    Costs,
    Entails,
    Reading,
    Satisfiable,
    Witness,
)
from elenctic.determination import Range
from elenctic.literals import Literal, Pattern, Symbol
from elenctic.query import All


def braces(literals: Iterable[Literal]) -> str:
    """Write literals as the `{ ... }` the contract syntax uses, in a fixed order."""
    return "{ " + ", ".join(map(str, sorted(literals))) + " }"


def _bindings(pattern: Pattern, found: frozenset[tuple[Symbol, ...]]) -> str:
    rows = sorted(",".join(map(str, row)) for row in found)
    return (
        "{ " + ", ".join(rows if len(pattern.variables) == 1 else [f"({r})" for r in rows]) + " }"
    )


def _optimally(over: Range) -> str:
    return "optimal " if over is Range.OPTIMAL else ""


def _of_models(reading: Census | Witness | Entails | Costs) -> str:
    match reading:
        case Census(count, over):
            return f"@count {_optimally(over)}{count}"
        case Witness(literals, over):
            return f"@model {_optimally(over)}{braces(literals)}"
        case Entails(mode, literals, over):
            return f"@{mode} {_optimally(over)}{braces(literals)}"
        case Costs(cost):
            return "@cost { " + " ".join(map(str, cost)) + " }"


def _reading(reading: Reading) -> str:
    match reading:
        case Satisfiable(expected):
            return f"@expect {'sat' if expected else 'unsat'}"
        case Census() | Witness() | Entails() | Costs():
            return _of_models(reading)
        case Asks(answer, All(parts)):
            return f"@query {answer} {braces(p for p in parts if isinstance(p, Literal))}"
        case Binds(answer, pattern, found):
            return f"@query {answer} {{ {pattern} }} = {_bindings(pattern, found)}"


def render(claim: Claim) -> str:
    """Write a claim as the tag line that reads back to it."""
    assumed = sorted(claim.scenario, key=lambda a: (a.literal, a.holds))
    assuming = ", ".join(("" if a.holds else "not ") + str(a.literal) for a in assumed)
    return _reading(claim.reading) + (f" assuming {{ {assuming} }}" if assumed else "")
