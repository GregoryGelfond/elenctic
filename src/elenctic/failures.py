"""Where a failed claim fails: what an entailment lacks, or what keeps a query from its answer."""

from collections.abc import Sequence

from elenctic.contract import Entails
from elenctic.determination import AnswerSet, Mode, Truncation
from elenctic.literals import Atoms, Literal
from elenctic.patterns import Pattern
from elenctic.query import All, Answer, Any, Query
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


def literals_of(query: Query) -> list[Literal]:
    """Name the literals a query is built of, in the order written."""
    match query:
        case Literal():
            return [query]
        case Pattern():
            closed = query.as_literal()
            return [] if closed is None else [closed]
        case All(parts) | Any(parts):
            return [literal for part in parts for literal in literals_of(part)]


def roots(query: Query, atoms: Atoms, answer: Answer) -> list[Literal]:
    """Name what keeps a query from having `answer` in one answer set.

    A `yes` wants each literal to hold, a `no` each contrary; one that does not is kept from it by
    what holds in its place (the other of the two), or else by its own absence.
    """
    if answer is Answer.UNKNOWN:
        return []
    wanted = [_wanted(literal, answer) for literal in literals_of(query)]
    return [w.contrary if w.contrary in atoms else w for w in wanted if w not in atoms]


def _wanted(literal: Literal, answer: Answer) -> Literal:
    return literal if answer is Answer.YES else literal.contrary
