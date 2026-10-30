"""Three-valued queries over a world view (Gelfond and Kahl, Definition 2.2.2, with its errata)."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from clingo import Symbol

from elenctic.determination import WorldView
from elenctic.literals import AnswerSet, Literal, Pattern


class Truth(IntEnum):
    """Truth in one answer set, ordered so conjunction is `min` and disjunction `max`."""

    FALSE = 0
    UNKNOWN = 1
    TRUE = 2


class Answer(StrEnum):
    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class All:
    """The conjunction of its parts."""

    parts: tuple[Query, ...]


@dataclass(frozen=True, slots=True)
class Any:
    """The disjunction of its parts."""

    parts: tuple[Query, ...]


type Query = Literal | All | Any


def evaluate(query: Query, member: AnswerSet) -> Truth:
    """Evaluate `query` in one answer set: a literal is true if in it, false if its contrary is."""
    match query:
        case Literal():
            return (
                Truth.TRUE
                if query in member
                else Truth.FALSE
                if query.contrary in member
                else Truth.UNKNOWN
            )
        case All(parts):
            return min((evaluate(part, member) for part in parts), default=Truth.TRUE)
        case Any(parts):
            return max((evaluate(part, member) for part in parts), default=Truth.FALSE)


def answer(query: Query, view: WorldView) -> Answer:
    """Yes if `query` is true in every answer set, no if false in every one, else unknown."""
    truths = {evaluate(query, member) for member in view.members}
    if truths == {Truth.TRUE}:
        return Answer.YES
    return Answer.NO if truths == {Truth.FALSE} else Answer.UNKNOWN


def singleton_answer(literal: Literal, cautious: AnswerSet) -> Answer:
    """Answer a single literal from the cautious consequences alone."""
    if literal in cautious:
        return Answer.YES
    return Answer.NO if literal.contrary in cautious else Answer.UNKNOWN


@dataclass(frozen=True, slots=True)
class Bindings:
    """The values of a pattern's variables that give each answer."""

    yes: frozenset[tuple[Symbol, ...]]
    no: frozenset[tuple[Symbol, ...]]
    unknown: frozenset[tuple[Symbol, ...]]


def bindings(pattern: Pattern, view: WorldView) -> Bindings:
    """Partition the instances of `pattern` some answer set entertains by their answer."""
    yes = pattern.bindings_in(view.cautious)
    no = pattern.contrary.bindings_in(view.cautious)
    entertained = pattern.bindings_in(view.brave) | pattern.contrary.bindings_in(view.brave)
    return Bindings(yes, no, entertained - yes - no)
