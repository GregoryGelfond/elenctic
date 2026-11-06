"""What a contract's claims must agree on, beyond each reading on its own."""

from elenctic.contract import Census, Claim, Satisfiable, denies_answer_sets
from elenctic.determination import Range
from elenctic.literals import Scenario
from elenctic.spans import Diagnostic, failure


def _expectations(claims: list[Claim], *, expect_seen: bool) -> list[Diagnostic]:
    expects = [c for c in claims if isinstance(c.reading, Satisfiable) and not c.scenario]
    absent = (
        [
            failure(
                None,
                "missing `@expect`",
                help=("add `% @expect sat` or `% @expect unsat`",),
            )
        ]
        if not expects and not expect_seen
        else []
    )
    return absent + [
        failure(c.span, "`@expect` given more than once", label="given again here")
        for c in expects[1:]
    ]


def _expecting(claims: list[Claim], *, satisfiable: bool) -> frozenset[Scenario]:
    """Name the scenarios in which the contract says `@expect sat` (or `unsat`)."""
    return frozenset(c.scenario for c in claims if c.reading == Satisfiable(satisfiable))


def _contradiction(
    claim: Claim, unsat: frozenset[Scenario], sat: frozenset[Scenario]
) -> Diagnostic | None:
    """Say how a claim contradicts the `@expect` of its own scenario, if it does."""
    reading = claim.reading
    admitted = isinstance(reading, Satisfiable) or denies_answer_sets(reading)
    if claim.scenario in unsat and not admitted:
        return failure(
            claim.span,
            "answer-set claim under `@expect unsat`",
            label="claims an answer set",
        )
    if claim.scenario in sat and isinstance(reading, Census) and reading.count == 0:
        word = "optimal " if reading.over is Range.OPTIMAL else ""
        return failure(
            claim.span,
            f"`@count {word}0` contradicts `@expect sat`",
            label="claims no answer set",
            help=("use `@expect unsat`",),
        )
    return None


def _exclusions(claims: list[Claim]) -> list[Diagnostic]:
    """Find claims that contradict the `@expect` of their own scenario."""
    unsat, sat = _expecting(claims, satisfiable=False), _expecting(claims, satisfiable=True)
    return [d for c in claims if (d := _contradiction(c, unsat, sat)) is not None]


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
            f"`@count optimal {c.reading.count}` exceeds `@count {counts[c.scenario, Range.ALL]}`",
            notes=("the optimal answer sets are among the answer sets",),
        )
        for c in claims
        if isinstance(c.reading, Census)
        and c.reading.over is Range.OPTIMAL
        and c.reading.count > counts.get((c.scenario, Range.ALL), c.reading.count)
    ]


def _repeated_counts(claims: list[Claim]) -> list[Diagnostic]:
    """Refuse a second `@count` for the same scenario and range."""
    seen: set[tuple[Scenario, Range]] = set()
    repeated: list[Diagnostic] = []
    for claim in claims:
        if not isinstance(claim.reading, Census):
            continue
        key = (claim.scenario, claim.reading.over)
        if key in seen:
            tag = "@count optimal" if claim.reading.over is Range.OPTIMAL else "@count"
            repeated.append(
                failure(
                    claim.span,
                    f"`{tag}` given more than once",
                    label="given again here",
                )
            )
        else:
            seen.add(key)
    return repeated


def wellformed(claims: list[Claim], *, expect_seen: bool = False) -> list[Diagnostic]:
    """Find what no single claim shows wrong: a missing or doubled `@expect`, and claims at odds.

    `expect_seen` is true when an `@expect` tag was written, even if it did not read: then
    `missing` is not emitted on top of that tag's own diagnostic.
    """
    return [
        *_expectations(claims, expect_seen=expect_seen),
        *_exclusions(claims),
        *_repeated_counts(claims),
        *_nested(claims),
    ]
