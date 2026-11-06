"""Three-valued queries over a world view (Gelfond and Kahl, Definition 2.2.2, with its errata)."""

from dataclasses import dataclass
from enum import IntEnum, StrEnum, auto
from functools import reduce

from elenctic.determination import WorldView
from elenctic.extension import Extension
from elenctic.literals import Atoms, Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.relation import Relation, Row
from elenctic.substitution import Substitution
from elenctic.terms import Variable
from elenctic.unify import unify

UNIT = Relation((), frozenset({()}))
NOTHING = Relation((), frozenset())


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


type Query = Literal | Pattern | All | Any


def evaluate(query: Query, member: Atoms) -> Truth:
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
    truths = {evaluate(query, member) for member in view.members}
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


def _entertained(query: Query, brave: Extension) -> Relation:
    """Join what each part of `query` entertains: the values its variables take in some part."""
    match query:
        case Literal():
            return _entertained(Pattern.of(query), brave)
        case Pattern():
            return _unifiers(query, brave).union(_unifiers(query.contrary, brave))
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
