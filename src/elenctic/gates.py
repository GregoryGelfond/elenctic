"""What would make a verdict untrustworthy: a claim asks what the program or the solver lacks."""

from elenctic.contract import Asks, Assigns, Binds, Claim, Contract, Reading, Solver, Witness, over
from elenctic.determination import Range
from elenctic.facts import Facts
from elenctic.grounded import Grounded
from elenctic.literals import Literal, Signature
from elenctic.patterns import Pattern
from elenctic.query import All, Any, Query
from elenctic.spans import Diagnostic, Span, failure, note

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


def _parts(query: Query) -> list[Literal | Pattern]:
    """List the literals and patterns a query reads, however deeply it nests them."""
    match query:
        case All(parts) | Any(parts):
            return [read for part in parts for read in _parts(part)]
        case _:
            return [query]


def _read(reading: Reading) -> frozenset[Signature]:
    """Name the predicates a query reads, whatever its answer."""
    match reading:
        case Asks(_, query):
            return frozenset(part.signature for part in _parts(query))
        case Binds(_, pattern, _):
            return frozenset({pattern.signature})
        case _:
            return frozenset()


def unsound(contract: Contract, grounded: Grounded) -> list[Diagnostic]:
    """Find what would make a verdict untrustworthy: a claim asks what the program lacks."""
    at_program = [
        failure(span, message) for span, message in _theoretical(contract.solver, grounded.facts)
    ]
    return at_program + [
        failure(claim.span, message)
        for claim in contract.claims
        for message in _lacks(claim.reading, grounded, contract.solver)
    ]


def hidden_reads(claims: list[Claim] | tuple[Claim, ...], grounded: Grounded) -> list[Diagnostic]:
    """Note each query that reads a literal the program can derive and does not `#show`.

    Queries evaluate over the full answer sets, so a hidden literal does not change the answer;
    the note marks that the claim looks past what `#show` selects. A later `--strict` may promote
    these notes to faults; that flag is not built yet.
    """
    return [
        note(
            claim.span,
            f"reads `{signature}`, which the program can derive and does not `#show`",
        )
        for claim in claims
        for signature in sorted(_read(claim.reading))
        if signature in grounded.signatures and not grounded.facts.shown.covers(signature)
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
    assigned = [_UNASSIGNED] * (solver is Solver.CLINGO and _assigning(reading))
    return objective + assigned
