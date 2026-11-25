"""What would make a verdict untrustworthy: a claim asks what the program or the solver lacks."""

from elenctic.contract import (
    Asks,
    Assigns,
    Binds,
    Claim,
    Contract,
    Reading,
    Satisfiable,
    Solver,
    Witness,
    over,
)
from elenctic.determination import Range
from elenctic.facts import Facts
from elenctic.grounded import Grounded
from elenctic.literals import Literal, Signature
from elenctic.patterns import Pattern
from elenctic.query import All, Any, Not, Query
from elenctic.spans import Diagnostic, Span, failure, note


def _parts(query: Query) -> list[Literal | Pattern | Not]:
    """List the literals and patterns a query reads, however deeply it nests them."""
    match query:
        case All(parts) | Any(parts):
            return [read for part in parts for read in _parts(part)]
        case _:
            return [query]


def _contrary(signature: Signature) -> Signature:
    return Signature(signature.name, signature.arity, not signature.positive)


def _signatures(part: Literal | Pattern | Not) -> frozenset[Signature]:
    """Return the signature a part reads, and its contrary (Gelfond-Kahl answers read both).

    `not l` reads only whether `l` holds.
    """
    if isinstance(part, Not):
        return frozenset({part.part.signature})
    signature = part.signature
    return frozenset({signature, _contrary(signature)})


def _read(reading: Reading) -> frozenset[Signature]:
    """Name the predicates a query reads, including each contrary, whatever its answer."""
    match reading:
        case Asks(_, query) | Binds(_, query, _):
            return frozenset[Signature]().union(*(_signatures(part) for part in _parts(query)))
        case _:
            return frozenset()


def unsound(contract: Contract, grounded: Grounded) -> list[Diagnostic]:
    """Find what would make a verdict untrustworthy: a claim asks what the program lacks."""
    return [
        *theoretical(
            contract.solver,
            grounded.facts,
            answers=not all(isinstance(claim.reading, Satisfiable) for claim in contract.claims),
        ),
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


def theoretical(solver: Solver, facts: Facts, *, answers: bool = True) -> list[Diagnostic]:
    """Find theory atoms clingo ignores, or a theory objective that reading answer sets cannot use.

    `answers` says whether anything is read of the answer sets beyond that one exists: clingcon
    applies a theory objective in every search, so the answer sets read are only its optima.
    """
    if facts.theory is not None and solver is Solver.CLINGO:
        return [
            failure(
                facts.theory,
                "clingo ignores theory atoms",
                label="theory atom",
                help=("declare `% @elenctic solver clingcon` to check them with clingcon",),
            )
        ]
    if facts.objective is not None and answers:
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


def lacks_objective(where: Span | None, asking: str) -> Diagnostic:
    """Refuse the optimal answer sets of a program that ranks none: Opt(P) needs an objective."""
    return failure(
        where,
        f"{asking}, but the program has no objective",
        label="needs an objective",
        notes=(
            (
                "the program declares no `#minimize`, `#maximize`, or `:~`, "
                "or its elements ground away"
            ),
        ),
    )


def _lacks(claim: Claim, grounded: Grounded, solver: Solver) -> list[Diagnostic]:
    reading = claim.reading
    objective = [lacks_objective(claim.span, "optimal claim")] * (
        over(reading) is Range.OPTIMAL and not grounded.facts.optimizes
    )
    assigned = [
        failure(
            claim.span,
            "claim reads a theory assignment, but no theory solver is declared",
            label="reads an assignment",
            help=("declare `% @elenctic solver clingcon`",),
        )
    ] * (solver is Solver.CLINGO and _assigning(reading))
    return objective + assigned
