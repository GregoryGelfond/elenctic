"""Three-valued queries over a world view (Gelfond and Kahl, Definition 2.2.2, with its errata)."""

from collections.abc import Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, replace
from enum import IntEnum, StrEnum, auto
from typing import Final, override

from elenctic.determination import AnswerSet, Range, Refutation, Truncation, WorldView
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
    """The answer of a query: yes, no or unknown by default; yes, or what else each mode says."""

    YES = auto()
    NO = auto()
    UNKNOWN = auto()
    NOT_ENTAILED = auto()
    """Cautious: false or unknown in some answer set."""
    NONE_HOLDS = auto()
    """Brave: true in no answer set."""


class AnswerMode(StrEnum):
    """How a query is answered over the answer sets, from its truth in each one."""

    DEFAULT = auto()
    """Gelfond and Kahl's three values: yes if true in every one, no if false in every one."""
    CAUTIOUS = auto()
    """Yes if true in every one, else not entailed."""
    BRAVE = auto()
    """Yes if true in some one, else none holds."""


ANSWERS: Final[Mapping[AnswerMode, tuple[Answer, ...]]] = {
    AnswerMode.DEFAULT: (Answer.YES, Answer.NO, Answer.UNKNOWN),
    AnswerMode.CAUTIOUS: (Answer.YES, Answer.NOT_ENTAILED),
    AnswerMode.BRAVE: (Answer.YES, Answer.NONE_HOLDS),
}
"""The answers each mode gives, in the order they are shown."""


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


def answer(query: Query, view: WorldView, *, mode: AnswerMode = AnswerMode.DEFAULT) -> Answer:
    """Answer `query` over the answer sets of `view`, from its truth in each, as `mode` does."""
    return decided({evaluate(query, member) for member in view.members}, mode)


def decided(truths: AbstractSet[Truth], mode: AnswerMode = AnswerMode.DEFAULT) -> Answer:
    """Answer from the truths a query takes in the answer sets, as `mode` does.

    Default: yes if only true, no if only false, else unknown. Cautious: yes if only true, else
    not entailed. Brave: yes if ever true, else none holds.
    """
    match mode:
        case AnswerMode.DEFAULT if truths == {Truth.TRUE}:
            return Answer.YES
        case AnswerMode.DEFAULT:
            return Answer.NO if truths == {Truth.FALSE} else Answer.UNKNOWN
        case AnswerMode.CAUTIOUS:
            return Answer.YES if truths == {Truth.TRUE} else Answer.NOT_ENTAILED
        case AnswerMode.BRAVE:
            return Answer.YES if Truth.TRUE in truths else Answer.NONE_HOLDS


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
class Bound:
    """A binding of a query's variables, their values in order of first occurrence, and its answer.

    `taken` names the first answer set to give each answer its instance takes there alone.
    """

    values: tuple[Symbol, ...]
    answer: Answer
    taken: tuple[Taken, ...]


@dataclass(frozen=True, slots=True)
class Answers:
    """The bindings of a query's variables, each with its answer, in the order they are shown.

    They are in the order their mode shows its answers, yes first, then in symbol order. Only the
    bindings each part without `not` entertains are answered: another instance is in no answer set.
    """

    variables: tuple[str, ...]
    bound: tuple[Bound, ...]

    def giving(self, answer: Answer) -> frozenset[tuple[Symbol, ...]]:
        """Return the values of the bindings with `answer`."""
        return frozenset(each.values for each in self.bound if each.answer is answer)

    def count(self, answer: Answer) -> int:
        """Count the bindings with `answer`."""
        return sum(1 for each in self.bound if each.answer is answer)


type _Part = Literal | Pattern | Not


def _pattern(part: Literal | Pattern) -> Pattern:
    return part if isinstance(part, Pattern) else Pattern.of(part)


def _leaves(query: Query) -> Iterator[tuple[Pattern, bool]]:
    """Yield the literals and patterns a query reads, each with whether `not` is before it."""
    match query:
        case All(parts) | Any(parts):
            for part in parts:
                yield from _leaves(part)
        case Not(part):
            yield _pattern(part), True
        case _:
            yield _pattern(query), False


def variables_of(query: Query) -> tuple[Variable, ...]:
    """Return the distinct named variables of a query, in order of first occurrence."""
    return tuple(dict.fromkeys(v for pattern, _ in _leaves(query) for v in pattern.variables))


def _conjuncts(query: Query) -> tuple[_Part, ...]:
    """Return the parts of a conjunction, nested ones taken apart; a disjunction is refused."""
    match query:
        case All(parts):
            return tuple(each for part in parts for each in _conjuncts(part))
        case Any():
            message = f"`{query}` is a disjunction, whose variables have no bindings to give"
            raise ValueError(message)
        case _:
            return (query,)


def unbound_of(query: Query) -> tuple[Variable, ...]:
    """Return the variables of a query that occur only under `not`, which no other part binds."""
    bound = {v for pattern, negated in _leaves(query) if not negated for v in pattern.variables}
    return tuple(v for v in variables_of(query) if v not in bound)


def _safe(query: Query) -> None:
    """Refuse a query with a variable only under `not`: its instances have no bound."""
    unbound = unbound_of(query)
    if unbound:
        message = f"variable `{unbound[0].name}` occurs only under `not`, so no part binds it"
        raise ValueError(message)


def _candidates(parts: tuple[_Part, ...], brave: Extension, mode: AnswerMode) -> Relation:
    """Return the bindings each part without `not` entertains: some answer set has its instance.

    By default an instance whose contrary some answer set has is entertained too, for it may be
    false; cautious and brave read only its truth.
    """
    found = Relation((), frozenset({()}))
    for part in parts:
        if not isinstance(part, Not):
            pattern = _pattern(part)
            read = _entertained if mode is AnswerMode.DEFAULT else _unifiers
            found = found.join(read(pattern, brave))
    return found


def _instance(parts: tuple[_Part, ...], substitution: Substitution) -> All:
    """Return the conjunction of the parts' instances under `substitution`, which grounds them."""

    def closed(part: Literal | Pattern) -> Literal:
        return _closed(_pattern(part).apply(substitution))

    return All(tuple(Not(closed(p.part)) if isinstance(p, Not) else closed(p) for p in parts))


type _Judged = tuple[Row, Answer, dict[Answer, int]]
"""A binding's values, its answer, and the index of the first member to give each answer alone."""


def _judged(query: Query, members: Sequence[Atoms], mode: AnswerMode) -> list[_Judged]:
    """Answer each binding of `query` some member entertains, in the order they are shown."""
    parts = _conjuncts(query)
    _safe(query)
    variables = variables_of(query)
    candidates = _candidates(parts, Extension(frozenset[Literal]().union(*members)), mode)
    at = candidates.indices(variables)
    judged: list[_Judged] = []
    for row in candidates.rows:
        values = tuple(row[i] for i in at)
        instance = _instance(parts, Substitution(dict(zip(variables, values, strict=True))))
        truths: set[Truth] = set()
        first: dict[Answer, int] = {}
        for index, member in enumerate(members, 1):
            truth = evaluate(instance, member)
            truths.add(truth)
            first.setdefault(_ALONE[truth], index)
        judged.append((values, decided(truths, mode), first))
    order = ANSWERS[mode]
    return sorted(judged, key=lambda each: (order.index(each[1]), each[0]))


def answers(
    query: Query, members: Sequence[AnswerSet], *, mode: AnswerMode = AnswerMode.DEFAULT
) -> Answers:
    """Answer each binding of a query's variables over answer sets given in the order read.

    Raises `ValueError` for a disjunction, a variable only under `not`, or `_`.
    """
    judged = _judged(query, [member.atoms for member in members], mode)
    return Answers(
        tuple(v.name for v in variables_of(query)),
        tuple(
            Bound(
                values,
                answer_,
                tuple(Taken(each, at, members[at - 1]) for each, at in first.items()),
            )
            for values, answer_, first in judged
        ),
    )


def bindings(pattern: Pattern | All, view: WorldView) -> Bindings:
    """Partition the bindings of a pattern, or a conjunction, by their answer over `view`.

    Each binding its parts without `not` entertain is answered by default over the answer sets.
    For one pattern, that is its unifiers with the cautious consequences (yes) and with their
    contraries (no), and with the brave ones for the rest it entertains (unknown).
    """
    judged = _judged(pattern, tuple(view.members), AnswerMode.DEFAULT)
    grouped = {
        each: frozenset(v for v, a, _ in judged if a is each)
        for each in ANSWERS[AnswerMode.DEFAULT]
    }
    return Bindings(grouped[Answer.YES], grouped[Answer.NO], grouped[Answer.UNKNOWN])


@dataclass(frozen=True, slots=True)
class Answered:
    """A query answered over the answer sets of a search, and the first to give each answer alone.

    `read` counts the answer sets when the search read them all, and is `None` when it stopped once
    each answer was given, or was cut first. Each answer given only past what it read is
    `unreached`.
    """

    query: Query
    over: Range
    answer: Answer | Answers
    taken: tuple[Taken, ...]
    read: int | None
    unreached: tuple[Unreached, ...] = ()
    mode: AnswerMode = AnswerMode.DEFAULT
    cut: Truncation | None = None


_ALONE: Final = {Truth.TRUE: Answer.YES, Truth.FALSE: Answer.NO, Truth.UNKNOWN: Answer.UNKNOWN}
"""The answer a query has in one answer set, from its truth there."""


def answered(
    query: Query,
    members: Sequence[AnswerSet],
    over: Range = Range.ALL,
    mode: AnswerMode = AnswerMode.DEFAULT,
) -> Answered:
    """Answer `query` as `mode` does over every answer set of a search, in the order it read them.

    A query with variables is answered by its bindings; it takes no one answer in an answer set.
    """
    read = len(members)
    if variables_of(query):
        return Answered(query, over, answers(query, members, mode=mode), (), read, mode=mode)
    found = answer(query, WorldView(frozenset(member.atoms for member in members), over), mode=mode)
    return Answered(query, over, found, taken(query, members), read, mode=mode)


def bravely(
    query: Query, members: Sequence[AnswerSet], over: Range, cut: Truncation
) -> Answered | None:
    """Answer `query` bravely from the answer sets a search read before `cut` stopped it.

    A `yes` found holds whatever the search would have read next, so it is kept, and `cut` says the
    rest is unread; with no `yes`, there is nothing to say.
    """
    found = answered(query, members, over, AnswerMode.BRAVE)
    kept = found.answer
    if isinstance(kept, Answers):
        yes = tuple(each for each in kept.bound if each.answer is Answer.YES)
        kept = Answers(kept.variables, yes)
    held = kept.count(Answer.YES) if isinstance(kept, Answers) else kept is Answer.YES
    return replace(found, answer=kept, read=None, cut=cut) if held else None


_SHOWN: Final[Mapping[AnswerMode, frozenset[Answer]]] = {
    AnswerMode.DEFAULT: frozenset({Answer.YES, Answer.NO}),
    AnswerMode.CAUTIOUS: frozenset({Answer.YES}),
    AnswerMode.BRAVE: frozenset({Answer.YES}),
}
"""The answers whose bindings are shown in each mode; the others are only counted."""


def stream(result: Answered, *, unknown: bool = False) -> Iterator[Bound]:
    """Yield the bindings of an answered query in the order they are shown, each one a `;`.

    A ground query yields its one answer, with no values. Bindings with `unknown` are yielded only
    when asked for, and in cautious and brave modes only `yes` bindings are.
    """
    found = result.answer
    if not isinstance(found, Answers):
        yield Bound((), found, result.taken)
        return
    shown = _SHOWN[result.mode] | {Answer.UNKNOWN} if unknown else _SHOWN[result.mode]
    yield from (each for each in found.bound if each.answer in shown)


def instance_of(query: Query, values: tuple[Symbol, ...]) -> Query:
    """Ground a query by the values of its variables, in order of first occurrence.

    A query without variables is its own instance; a pattern's is the conjunction of its one part.
    """
    variables = variables_of(query)
    if not variables:
        return query
    substitution = Substitution(dict(zip(variables, values, strict=True)))
    return _instance(_conjuncts(query), substitution)


type Body = tuple[str, ...]
"""The literals of a rule body as clingo writes them, `not` before any."""


def bodies(query: Query, truth: Truth) -> tuple[Body, ...]:
    """Write bodies, one of which holds in an answer set exactly when a ground query has `truth`.

    `l` is true where it is and false where its contrary is; `not l` is true where `l` is not and
    false where it is. A conjunction is true where all its parts are and false where one is false;
    a disjunction is the converse. Raises `ValueError` for a truth other than true or false.
    """
    if truth is Truth.UNKNOWN:
        message = "an unknown query has no body: it is neither true nor false"
        raise ValueError(message)
    match query:
        case Literal():
            return ((str(query if truth is Truth.TRUE else query.contrary),),)
        case Not(Literal() as part):
            return ((f"not {part}" if truth is Truth.TRUE else str(part),),)
        case All(parts) | Any(parts):
            each = [bodies(part, truth) for part in parts]
            if (truth is Truth.TRUE) is isinstance(query, All):
                return _product(each)
            return tuple(body for found in each for body in found)
        case _:
            message = f"`{query}` has variables: ground it first"
            raise ValueError(message)


def _product(each: Sequence[tuple[Body, ...]]) -> tuple[Body, ...]:
    """Conjoin disjunctions of bodies: one body for each choice of a body from each."""
    found: tuple[Body, ...] = ((),)
    for disjunction in each:
        found = tuple((*left, *right) for left in found for right in disjunction)
    return found


@dataclass(frozen=True, slots=True)
class Warrant:
    """What shows the answer of a ground query, or of one binding: the instance it is about.

    `witnesses` are answer sets that show it, each with the answer the instance takes there alone:
    one where it is true for a `yes`, false for a `no`; for an `unknown`, one where it is not true
    and one where it is not false, one answer set when it is unknown there. An answer that needs
    every answer set also has the `refutation` of the program asked for one that would overturn it.
    """

    query: Query
    answer: Answer
    witnesses: tuple[Taken, ...]
    refutation: Refutation | None


_WITNESSED: Final[Mapping[Answer, tuple[frozenset[Answer], ...]]] = {
    Answer.YES: (frozenset({Answer.YES}),),
    Answer.NO: (frozenset({Answer.NO}),),
    Answer.UNKNOWN: (
        frozenset({Answer.NO, Answer.UNKNOWN}),
        frozenset({Answer.YES, Answer.UNKNOWN}),
    ),
    Answer.NOT_ENTAILED: (frozenset({Answer.NO, Answer.UNKNOWN}),),
    Answer.NONE_HOLDS: (),
}
"""For each answer, the answers alone that each of its witnesses may take, in the order shown."""


def witnessed(answer: Answer, taken: Sequence[Taken]) -> tuple[Taken, ...]:
    """Choose the witnesses of an answer from the first answer sets to give each answer alone."""
    found: list[Taken] = []
    for wanted in _WITNESSED[answer]:
        first = min((each for each in taken if each.answer in wanted), key=lambda each: each.index)
        if first not in found:
            found.append(first)
    return tuple(found)


class Held(StrEnum):
    """Where an answer needs a query to have a truth: in every answer set, or in none."""

    EVERYWHERE = auto()
    NOWHERE = auto()


REFUTED: Final[Mapping[tuple[AnswerMode, Answer], tuple[Truth, Held]]] = {
    (AnswerMode.DEFAULT, Answer.YES): (Truth.TRUE, Held.EVERYWHERE),
    (AnswerMode.CAUTIOUS, Answer.YES): (Truth.TRUE, Held.EVERYWHERE),
    (AnswerMode.DEFAULT, Answer.NO): (Truth.FALSE, Held.EVERYWHERE),
    (AnswerMode.BRAVE, Answer.NONE_HOLDS): (Truth.TRUE, Held.NOWHERE),
}
"""The answers that need every answer set: the truth each needs the query to have, and where."""


@dataclass(frozen=True, slots=True)
class ReadAnswers:
    """How a search read answer sets: those read, what cut it, and the count if exhausted."""

    members: Sequence[AnswerSet]
    cut: Truncation | None
    count: int | None


def settled(
    query: Query,
    reading: ReadAnswers,
    truths: AbstractSet[Truth],
    mode: AnswerMode = AnswerMode.DEFAULT,
) -> Answered:
    """Answer `query` from the truths some answer set gives it, and the first of `members` to.

    `members` are the answer sets a search read, in its order, until each truth was given or `cut`
    stopped it: an answer none of them gives is unreached. `read` counts them if they are all.
    """
    members, cut, read = reading.members, reading.cut, reading.count
    first = taken(query, members)
    given = {each.answer for each in first}
    wanted = {_ALONE[truth] for truth in truths}
    unreached = tuple(
        Unreached(each, len(members), cut)
        for each in ANSWERS[AnswerMode.DEFAULT]
        if cut is not None and each in wanted and each not in given
    )
    return Answered(query, Range.ALL, decided(truths, mode), first, read, unreached, mode)


def taken(query: Query, members: Sequence[AnswerSet]) -> tuple[Taken, ...]:
    """Find the first of `members`, in their order, to give each answer `query` takes alone."""
    first: dict[Answer, Taken] = {}
    for index, member in enumerate(members, 1):
        alone = _ALONE[evaluate(query, member.atoms)]
        first.setdefault(alone, Taken(alone, index, member))
    return tuple(first.values())
