"""What would make a verdict untrustworthy: a claim asks what the program or the solver lacks."""

from elenctic.contract import Asks, Assigns, Binds, Contract, Reading, Solver, Witness, over
from elenctic.determination import Range
from elenctic.engine import Facts, Grounded
from elenctic.literals import Literal, Signature
from elenctic.query import Answer
from elenctic.spans import Diagnostic, Severity, Span

_IGNORED = (
    "the program has theory atoms, which clingo would ground and ignore; "
    "declare `% @elenctic solver clingcon` to check them with clingcon"
)
_OBJECTIVE = (
    "the program has a theory objective, which clingcon applies in every search and clingo's "
    "cost does not see; state the objective with `#minimize` or `#maximize`"
)
_UNASSIGNED = (
    "reads a theory assignment, but the contract declares no theory solver: "
    "declare `% @elenctic solver clingcon`"
)


def _contraries(reading: Reading) -> frozenset[Signature]:
    """Name the predicates a `no` or `unknown` query reads as contraries off the shown atoms."""
    match reading:
        case Asks(Answer.NO | Answer.UNKNOWN, query):
            return frozenset(
                part.contrary.signature for part in query.parts if isinstance(part, Literal)
            )
        case Binds(Answer.UNKNOWN, pattern, _):
            return frozenset({pattern.contrary.signature})
        case Binds(Answer.NO, pattern, found) if found:
            return frozenset({pattern.contrary.signature})
        case _:
            return frozenset()


def unsound(contract: Contract, grounded: Grounded) -> list[Diagnostic]:
    """Find what would make a verdict untrustworthy: a claim asks what the program lacks."""
    at_program = [
        Diagnostic(span, Severity.ERROR, message)
        for span, message in _theoretical(contract.solver, grounded.facts)
    ]
    return at_program + [
        Diagnostic(claim.span, Severity.ERROR, message)
        for claim in contract.claims
        for message in _lacks(claim.reading, grounded, contract.solver)
    ]


def _theoretical(solver: Solver, facts: Facts) -> list[tuple[Span, str]]:
    """Find theory atoms clingo would ignore, or a theory objective clingcon cannot switch off."""
    if facts.theory is not None and solver is Solver.CLINGO:
        return [(facts.theory, _IGNORED)]
    if facts.objective is not None:
        return [(facts.objective, _OBJECTIVE)]
    return []


def _assigning(reading: Reading) -> bool:
    return isinstance(reading, Assigns) or (
        isinstance(reading, Witness) and bool(reading.assignment)
    )


def _lacks(reading: Reading, grounded: Grounded, solver: Solver) -> list[str]:
    objective = [
        (
            "needs an objective, but the ground program has none: it declares no `#minimize`, "
            "`#maximize` or `:~`, or its elements ground away"
        )
    ] * (over(reading) is Range.OPTIMAL and not grounded.facts.optimizes)
    unshown = [
        f"reads the contrary `{signature}` off the shown atoms, "
        "but the program can derive it and does not `#show` it"
        for signature in sorted(_contraries(reading))
        if signature in grounded.signatures and not grounded.facts.shown.covers(signature)
    ]
    assigned = [_UNASSIGNED] * (solver is Solver.CLINGO and _assigning(reading))
    return objective + unshown + assigned
