"""Write a claim as the tag line that reads back to it."""

from collections.abc import Iterable

from elenctic.contract import (
    Asks,
    Assigns,
    Binds,
    Census,
    Claim,
    Costs,
    Entails,
    Reading,
    Satisfiable,
    Witness,
)
from elenctic.determination import Assignment, Range
from elenctic.literals import Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.query import All


def braces(literals: Iterable[Literal]) -> str:
    """Write literals as the `{ ... }` the contract syntax uses, in a fixed order."""
    parts = ", ".join(map(str, sorted(literals)))
    return "{ }" if not parts else "{ " + parts + " }"


def _bindings(pattern: Pattern, found: frozenset[tuple[Symbol, ...]]) -> str:
    rows = sorted(",".join(map(str, row)) for row in found)
    return (
        "{ " + ", ".join(rows if len(pattern.variables) == 1 else [f"({r})" for r in rows]) + " }"
    )


def _optimally(over: Range) -> str:
    return "optimal " if over is Range.OPTIMAL else ""


def bound(assignment: Assignment) -> str:
    """Write an assignment as the `{ term=integer, ... }` the contract syntax uses."""
    written = sorted(f"{v.variable}={v.value}" for v in assignment)
    return "{ }" if not written else "{ " + ", ".join(written) + " }"


def where(assignment: Assignment) -> str:
    """Write the ` where { ... }` that follows a witness, or nothing if it assigns nothing."""
    return f" where {bound(assignment)}" if assignment else ""


def _of_answer_sets(reading: Census | Witness | Assigns | Entails | Costs) -> str:
    match reading:
        case Census(count, over):
            return f"@count {_optimally(over)}{count}"
        case Witness(literals, over, assignment):
            return f"@answer-set {_optimally(over)}{braces(literals)}{where(assignment)}"
        case Assigns(assignment, over):
            return f"@assign {_optimally(over)}{bound(assignment)}"
        case Entails(mode, literals, over):
            return f"@{mode} {_optimally(over)}{braces(literals)}"
        case Costs(cost):
            return "@cost { " + " ".join(map(str, cost)) + " }"


def _reading(reading: Reading) -> str:
    match reading:
        case Satisfiable(expected):
            return f"@expect {'sat' if expected else 'unsat'}"
        case Census() | Witness() | Assigns() | Entails() | Costs():
            return _of_answer_sets(reading)
        case Asks(answer, All(parts), over):
            return (
                f"@query {_optimally(over)}{answer} "
                f"{braces(p for p in parts if isinstance(p, Literal))}"
            )
        case Binds(answer, pattern, bindings, over):
            return (
                f"@query {_optimally(over)}{answer} {{ {pattern} }} = "
                f"{_bindings(pattern, bindings)}"
            )


def render(claim: Claim) -> str:
    """Write a claim as the tag line that reads back to it."""
    assumed = sorted(claim.scenario, key=lambda a: (a.literal, a.holds))
    assuming = ", ".join(("" if a.holds else "not ") + str(a.literal) for a in assumed)
    return _reading(claim.reading) + (f" assuming {{ {assuming} }}" if assumed else "")
