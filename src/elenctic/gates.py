"""What would make a verdict untrustworthy: a claim asks what the program or the solver lacks."""

from elenctic.contract import Asks, Assigns, Binds, Claim, Contract, Reading, Solver, Witness, over
from elenctic.determination import Range
from elenctic.facts import Facts
from elenctic.grounded import Grounded
from elenctic.literals import Literal, Signature
from elenctic.patterns import Pattern
from elenctic.query import All, Any, Query
from elenctic.spans import Diagnostic, failure, note


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
    return [
        *_theoretical(contract.solver, grounded.facts),
        *(
            diagnostic
            for claim in contract.claims
            for diagnostic in _lacks(claim, grounded, contract.solver)
        ),
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


def _theoretical(solver: Solver, facts: Facts) -> list[Diagnostic]:
    """Find theory atoms clingo would ignore, or a theory objective clingcon cannot switch off."""
    if facts.theory is not None and solver is Solver.CLINGO:
        return [
            failure(
                facts.theory,
                "clingo ignores theory atoms",
                label="theory atom",
                help=("declare `% @elenctic solver clingcon` to check them with clingcon",),
            )
        ]
    if facts.objective is not None:
        return [
            failure(
                facts.objective,
                "theory objective is not seen by the cost",
                label="theory objective",
                notes=("clingcon applies it in every search",),
                help=("state the objective with `#minimize` or `#maximize`",),
            )
        ]
    return []


def _assigning(reading: Reading) -> bool:
    return isinstance(reading, Assigns) or (
        isinstance(reading, Witness) and bool(reading.assignment)
    )


def _lacks(claim: Claim, grounded: Grounded, solver: Solver) -> list[Diagnostic]:
    reading = claim.reading
    objective = [
        failure(
            claim.span,
            "optimal claim, but the program has no objective",
            label="needs an objective",
            notes=(
                (
                    "the program declares no `#minimize`, `#maximize`, or `:~`, "
                    "or its elements ground away"
                ),
            ),
        )
    ] * (over(reading) is Range.OPTIMAL and not grounded.facts.optimizes)
    assigned = [
        failure(
            claim.span,
            "claim reads a theory assignment, but no theory solver is declared",
            label="reads an assignment",
            help=("declare `% @elenctic solver clingcon`",),
        )
    ] * (solver is Solver.CLINGO and _assigning(reading))
    return objective + assigned
