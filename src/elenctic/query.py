"""Three-valued queries over a world view (Gelfond and Kahl, Definition 2.2.2, with its errata)."""

from collections.abc import Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto
from typing import Final, override

from elenctic.determination import AnswerSet, Range, Truncation, WorldView
from elenctic.extension import Extension
from elenctic.literals import Atoms, Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.relation import Relation, Row
from elenctic.substitution import Substitution
from elenctic.terms import Variable
from elenctic.unify import unify


class Truth(IntEnum):
    """Truth in one answer set, ordered so conjunction is `min` and disjunction `max`."""

    FALSE = 0
    UNKNOWN = 1
    TRUE = 2


class Answer(StrEnum):
    """The three-valued answer of a query: yes, no, or unknown."""

    YES = auto()
    NO = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class All:
    """The conjunction of its parts."""

    parts: tuple[Query, ...]


@dataclass(frozen=True, slots=True)
class Any:
    """The disjunction of its parts."""

    parts: tuple[Query, ...]


@dataclass(frozen=True, slots=True)
class Not:
    """Default negation: true in an answer set exactly when its literal is not in it."""

    part: Literal | Pattern

    @override
    def __str__(self) -> str:
        return f"not {self.part}"


type Query = Literal | Pattern | Not | All | Any


def evaluate(query: Query, member: Atoms) -> Truth:
    """Evaluate `query` in one answer set: a literal is true if in it, false if its contrary is.

    `not l` is true if `l` is not in it and false if it is, so it is never unknown. A pattern with
    variables has bindings rather than a truth, and is refused.
    """
    match query:
        case Pattern():
            return evaluate(_closed(query), member)
        case Not(part):
            literal = _closed(part) if isinstance(part, Pattern) else part
            return Truth.FALSE if literal in member else Truth.TRUE
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


def literal_of(query: Query) -> Literal | None:
    """Return the one literal `query` asks of, when it has the literal's truth; else `None`.

    A ground pattern is its literal, and a conjunction or disjunction of one part is that part.
    """
    match query:
        case Literal():
            return query
        case Pattern():
            return query.as_literal()
        case All((part,)) | Any((part,)):
            return literal_of(part)
        case _:
            return None


def answer(query: Query, view: WorldView) -> Answer:
    """Yes if `query` is true in every answer set, no if false in every one, else unknown.

    A literal is true in every answer set when it is a cautious consequence and false in every one
    when its contrary is, so it is answered from the cautious consequences alone.
    """
    if isinstance(query, Pattern):
        query = _closed(query)
    if isinstance(query, Literal):
        cautious = view.cautious
        return (
            Answer.YES
            if query in cautious
            else Answer.NO
            if query.contrary in cautious
            else Answer.UNKNOWN
        )
    return decided({evaluate(query, member) for member in view.members})


def decided(truths: AbstractSet[Truth]) -> Answer:
    """Answer from the truths a query takes: yes if only true, no if only false, else unknown."""
    if truths == {Truth.TRUE}:
        return Answer.YES
    return Answer.NO if truths == {Truth.FALSE} else Answer.UNKNOWN


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


def _row(variables: tuple[Variable, ...], unifier: Substitution) -> Row:
    """Return the values `unifier` gives `variables`: symbols, for it unified them with a fact."""
    return tuple(value for v in variables if isinstance(value := unifier.apply(v), Symbol))


def _unifiers(pattern: Pattern, facts: Extension) -> Relation:
    """Return the values of the variables of `pattern` in its most general unifier with each fact.

    A fact is ground, so renaming it apart from the pattern changes nothing: the unifier is the
    one `mgu` finds, over the pattern's own variables.
    """
    if pattern.anonymous:
        message = f"`{pattern}` has an anonymous variable, which no binding can name"
        raise ValueError(message)
    rows = frozenset(
        _row(pattern.variables, unifier)
        for fact in facts.with_signature(pattern.signature)
        if (unifier := unify(pattern, Pattern.of(fact))) is not None
    )
    return Relation(pattern.variables, rows)


def _entertained(pattern: Pattern, brave: Extension) -> Relation:
    """Return the values of `pattern`'s variables some answer set entertains.

    An instance counts when the pattern or its contrary unifies with a brave consequence.
    """
    return _unifiers(pattern, brave).union(_unifiers(pattern.contrary, brave))


def bindings(pattern: Pattern, view: WorldView) -> Bindings:
    """Partition the instances of `pattern` some answer set entertains by their answer.

    The cautious consequences are the facts the pattern is unified with: an instance is yes when
    it is one of them and no when its contrary is. The brave consequences add only the instances
    entertained and neither. Compound queries (conjunction, disjunction) are answered by `answer`;
    their bindings are not listed here.
    """
    cautious = Extension(view.cautious)
    brave = Extension(view.brave)
    yes = _unifiers(pattern, cautious).rows
    no = _unifiers(pattern.contrary, cautious).rows
    return Bindings(yes, no, _entertained(pattern, brave).rows - yes - no)


@dataclass(frozen=True, slots=True)
class Taken:
    """An answer a query takes in one answer set alone, and the first answer set that gives it."""

    answer: Answer
    index: int
    answer_set: AnswerSet


@dataclass(frozen=True, slots=True)
class Unreached:
    """An answer a query takes in some answer set alone, past the `read` answer sets searched.

    `cut` is what stopped the search before it reached the first answer set to give it.
    """

    answer: Answer
    read: int
    cut: Truncation


@dataclass(frozen=True, slots=True)
class Answered:
    """A query answered over the answer sets of a search, and the first to give each answer alone.

    `read` counts the answer sets when the search read them all, and is `None` when it stopped once
    each answer was given, or was cut first. Each answer given only past what it read is
    `unreached`.
    """

    query: Query
    over: Range
    answer: Answer | Bindings
    taken: tuple[Taken, ...]
    read: int | None
    unreached: tuple[Unreached, ...] = ()


_ALONE: Final = {Truth.TRUE: Answer.YES, Truth.FALSE: Answer.NO, Truth.UNKNOWN: Answer.UNKNOWN}
"""The answer a query has in one answer set, from its truth there."""


def answered(query: Query, members: Sequence[AnswerSet], over: Range = Range.ALL) -> Answered:
    """Answer `query` over every answer set of a search, given in the order it read them.

    A pattern with variables is answered by its bindings; it takes no one answer in an answer set.
    """
    view = WorldView(frozenset(member.atoms for member in members), over)
    if isinstance(query, Pattern) and query.variables:
        return Answered(query, over, bindings(query, view), (), len(members))
    return Answered(query, over, answer(query, view), taken(query, members), len(members))


def settled(
    query: Query,
    members: Sequence[AnswerSet],
    truths: AbstractSet[Truth],
    cut: Truncation | None,
    read: int | None,
) -> Answered:
    """Answer `query` from the truths some answer set gives it, and the first of `members` to.

    `members` are the answer sets a search read, in its order, until each truth was given or `cut`
    stopped it: an answer none of them gives is unreached. `read` counts them if they are all.
    """
    first = taken(query, members)
    given = {each.answer for each in first}
    wanted = {_ALONE[truth] for truth in truths}
    unreached = tuple(
        Unreached(each, len(members), cut)
        for each in Answer
        if cut is not None and each in wanted and each not in given
    )
    return Answered(query, Range.ALL, decided(truths), first, read, unreached)


def taken(query: Query, members: Sequence[AnswerSet]) -> tuple[Taken, ...]:
    """Find the first of `members`, in their order, to give each answer `query` takes alone."""
    first: dict[Answer, Taken] = {}
    for index, member in enumerate(members, 1):
        alone = _ALONE[evaluate(query, member.atoms)]
        first.setdefault(alone, Taken(alone, index, member))
    return tuple(first.values())
