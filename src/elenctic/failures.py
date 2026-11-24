"""Where a failed claim fails: what an entailment lacks, or what keeps a query from its answer."""

from collections.abc import Sequence

from elenctic.contract import Entails
from elenctic.determination import AnswerSet, Mode, Truncation
from elenctic.literals import Atoms, Literal
from elenctic.patterns import Pattern
from elenctic.query import All, Answer, Any, Not, Query
from elenctic.verdicts import Ended


def missing(
    entails: Entails, sets: Sequence[AnswerSet], *, closed: bool
) -> tuple[int, AnswerSet, list[Literal]] | Ended | None:
    """Find where an entailment fails: the answer set, its place, and the literals it lacks.

    Cautious fails in the first answer set without them all; brave, in the first answer set, for
    the literals no answer set has, which it can say only when it read them all.
    """
    if entails.mode is Mode.CAUTIOUS:
        return _first_lacking(entails.literals, sets)
    if not closed:
        return Ended(Truncation.MAX_ANSWER_SETS)
    seen_anywhere = frozenset[Literal]().union(*(s.shown for s in sets))
    return 1, sets[0], sorted(entails.literals - seen_anywhere)


def _first_lacking(
    literals: Atoms, sets: Sequence[AnswerSet]
) -> tuple[int, AnswerSet, list[Literal]] | None:
    for at, answer_set in enumerate(sets, 1):
        if not literals <= answer_set.shown:
            return at, answer_set, sorted(literals - answer_set.shown)
    return None


def roots(query: Query, atoms: Atoms, answer: Answer) -> list[Literal]:
    """Name what keeps a query from having `answer` in one answer set.

    A `yes` wants each part true, a `no` each part false. A literal kept from it is kept by what
    holds in its place (the other of the literal and its contrary), or else by its own absence;
    `not l` is kept from it by `l`, present for `yes` and absent for `no`.
    """
    if answer is Answer.UNKNOWN:
        return []
    return [root for part in _parts(query) if (root := _root(part, atoms, answer)) is not None]


def _parts(query: Query) -> list[Literal | Not]:
    """List the ground parts a query is built of, in the order written."""
    match query:
        case Literal():
            return [query]
        case Pattern():
            closed = query.as_literal()
            return [] if closed is None else [closed]
        case Not(part):
            closed = part.as_literal() if isinstance(part, Pattern) else part
            return [] if closed is None else [Not(closed)]
        case All(parts) | Any(parts):
            return [each for part in parts for each in _parts(part)]


def _root(part: Literal | Not, atoms: Atoms, answer: Answer) -> Literal | None:
    match part:
        case Not(Literal() as literal):
            return literal if (literal in atoms) is (answer is Answer.YES) else None
        case Literal():
            wanted = part if answer is Answer.YES else part.contrary
            if wanted in atoms:
                return None
            return wanted.contrary if wanted.contrary in atoms else wanted
        case _:
            return None
