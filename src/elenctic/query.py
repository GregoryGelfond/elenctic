"""Three-valued queries over a world view (Gelfond and Kahl, Definition 2.2.2, with its errata)."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from functools import reduce

from elenctic.determination import WorldView
from elenctic.extension import Extension
from elenctic.literals import AnswerSet, Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.relation import Relation
from elenctic.substitution import Substitution

UNIT = Relation((), frozenset({()}))
NOTHING = Relation((), frozenset())


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


type Query = Literal | Pattern | All | Any


def evaluate(query: Query, member: AnswerSet) -> Truth:
    """Evaluate `query` in one answer set: a literal is true if in it, false if its contrary is.

    A pattern with variables has bindings rather than a truth, and is refused.
    """
    match query:
        case Pattern():
            return evaluate(_closed(query), member)
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

    def giving(self, answer: Answer) -> frozenset[tuple[Symbol, ...]]:
        """Return the values that give `answer`."""
        return {Answer.YES: self.yes, Answer.NO: self.no, Answer.UNKNOWN: self.unknown}[answer]


def _closed(pattern: Pattern) -> Literal:
    literal = pattern.as_literal()
    if literal is None:
        message = f"`{pattern}` has variables, so it has bindings rather than an answer"
        raise ValueError(message)
    return literal


def _entertained(query: Query, brave: Extension) -> Relation:
    """Join what each part of `query` entertains: the values its variables take in some part."""
    match query:
        case Literal():
            return _entertained(Pattern.of(query), brave)
        case Pattern():
            found = query.bindings_in(brave) | query.contrary.bindings_in(brave)
            return Relation(query.variables, found)
        case All(parts):
            return reduce(Relation.join, (_entertained(p, brave) for p in parts), UNIT)
        case Any(parts):
            each = [_entertained(part, brave) for part in parts]
            return reduce(Relation.union, each) if each else NOTHING


def _instance(query: Query, values: Substitution) -> Query:
    match query:
        case Literal():
            return query
        case Pattern():
            return _closed(query.apply(values))
        case All(parts):
            return All(tuple(_instance(part, values) for part in parts))
        case Any(parts):
            return Any(tuple(_instance(part, values) for part in parts))


def bindings(query: Query, view: WorldView) -> Bindings:
    """Partition the instances of `query` some answer set entertains by their answer.

    The variables of a query are those of its parts, in order of first occurrence. An instance
    is entertained when every part of a conjunction has an instance, or its contrary has, in
    some answer set, and when some part of a disjunction has; an instance the world view says
    nothing about is unknown to it, but is not listed, for there are infinitely many.
    """
    found = _entertained(query, Extension(view.brave))
    answered = {
        row: answer(
            _instance(query, Substitution(dict(zip(found.columns, row, strict=True)))), view
        )
        for row in found.rows
    }
    return Bindings(*(frozenset(r for r, a in answered.items() if a is each) for each in Answer))
