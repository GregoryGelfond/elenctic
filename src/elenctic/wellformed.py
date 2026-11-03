"""What a contract's claims must agree on, beyond each reading on its own."""

from elenctic.contract import Census, Claim, Satisfiable, denies_answer_sets
from elenctic.determination import Range
from elenctic.literals import Scenario
from elenctic.spans import Diagnostic, Position, Span, failure


def _expectations(claims: list[Claim], source: str) -> list[Diagnostic]:
    expects = [c for c in claims if isinstance(c.reading, Satisfiable) and not c.scenario]
    start = Span(source, Position(1, 1), Position(1, 1))
    absent = [failure(start, "missing `@expect`")] if not expects else []
    return absent + [failure(c.span, "more than one `@expect`") for c in expects[1:]]


def _expecting(claims: list[Claim], *, satisfiable: bool) -> frozenset[Scenario]:
    """Name the scenarios in which the contract says `@expect sat` (or `unsat`)."""
    return frozenset(c.scenario for c in claims if c.reading == Satisfiable(satisfiable))


def _contradiction(
    claim: Claim, unsat: frozenset[Scenario], sat: frozenset[Scenario]
) -> str | None:
    """Say how a claim contradicts the `@expect` of its own scenario, if it does."""
    reading = claim.reading
    admitted = isinstance(reading, Satisfiable) or denies_answer_sets(reading)
    if claim.scenario in unsat and not admitted:
        return "`@expect unsat` admits no answer set claim"
    if claim.scenario in sat and denies_answer_sets(reading):
        return "`@count 0` is `@expect unsat`, not `@expect sat`"
    return None


def _exclusions(claims: list[Claim]) -> list[Diagnostic]:
    """Find claims that contradict the `@expect` of their own scenario."""
    unsat, sat = _expecting(claims, satisfiable=False), _expecting(claims, satisfiable=True)
    return [failure(c.span, message) for c in claims if (message := _contradiction(c, unsat, sat))]


def _nested(claims: list[Claim]) -> list[Diagnostic]:
    """Find an `@count optimal n` above the `@count m` of its scenario: Opt(P) ⊆ AS(P)."""
    counts = {
        (c.scenario, c.reading.over): c.reading.count
        for c in claims
        if isinstance(c.reading, Census)
    }
    return [
        failure(
            c.span,
            f"`@count optimal {c.reading.count}` exceeds `@count {counts[c.scenario, Range.ALL]}`: "
            "the optimal answer sets are among the answer sets",
        )
        for c in claims
        if isinstance(c.reading, Census)
        and c.reading.over is Range.OPTIMAL
        and c.reading.count > counts.get((c.scenario, Range.ALL), c.reading.count)
    ]


def wellformed(claims: list[Claim], source: str) -> list[Diagnostic]:
    """Find what no single claim shows wrong: a missing or doubled `@expect`, and claims at odds."""
    return [*_expectations(claims, source), *_exclusions(claims), *_nested(claims)]
