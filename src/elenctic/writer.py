"""Write a claim as the tag line that reads back to it."""

from collections.abc import Iterable
from operator import itemgetter

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
from elenctic.query import All, Not, Query


def braces(literals: Iterable[Literal]) -> str:
    """Write literals as the `{ ... }` the contract syntax uses, in a fixed order."""
    parts = ", ".join(map(str, sorted(literals)))
    return "{ }" if not parts else "{ " + parts + " }"


def rows(pattern: Pattern, found: Iterable[tuple[Symbol, ...]]) -> str:
    """Write bindings of a pattern as the `{ ... }` the contract syntax uses, in symbol order.

    A binding of one variable is written bare, `2`; of several, as a tuple, `(b,2)`.
    """
    terms = [",".join(map(str, row)) for row in sorted(found)]
    written = terms if len(pattern.variables) == 1 else [f"({each})" for each in terms]
    return "{ }" if not written else "{ " + ", ".join(written) + " }"


def queried(query: All | Pattern) -> str:
    """Write a query as `@query` does: its parts in braces, or its one pattern.

    Ground parts are written in a fixed order; parts with variables, as written, since the order
    their variables first occur in is the order of each binding's values.
    """
    if isinstance(query, Pattern):
        return f"{{ {query} }}"
    keys = [_order(part) for part in query.parts]
    ordered = (
        query.parts
        if None in keys
        else [part for _, part in sorted(zip(keys, query.parts, strict=True), key=itemgetter(0))]
    )
    parts = ", ".join(map(str, ordered))
    return "{ }" if not parts else "{ " + parts + " }"


def _order(part: Query) -> tuple[Literal, bool] | None:
    """Order a ground part by its literal, with `not` after it without; `None` if not ground."""
    match part:
        case Literal():
            return part, False
        case Not(Literal() as literal):
            return literal, True
        case _:
            return None


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
        case Asks(answer, query, over):
            return f"@query {_optimally(over)}{answer} {queried(query)}"
        case Binds(answer, pattern, bindings, over):
            return f"@query {_optimally(over)}{answer} {{ {pattern} }} = {rows(pattern, bindings)}"


def render(claim: Claim) -> str:
    """Write a claim as the tag line that reads back to it."""
    assumed = sorted(claim.scenario)
    assuming = ", ".join(("" if a.holds else "not ") + str(a.literal) for a in assumed)
    return _reading(claim.reading) + (f" assuming {{ {assuming} }}" if assumed else "")
