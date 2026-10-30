"""The contract: the claims a program is held to, as a vocabulary of readings."""

from dataclasses import dataclass

from elenctic.determination import Cost, Mode, Range
from elenctic.literals import AnswerSet, Pattern, Scenario, Symbol
from elenctic.query import All, Answer
from elenctic.spans import Diagnostic, Span


@dataclass(frozen=True, slots=True)
class Satisfiable:
    """`@expect sat | unsat`: whether the program has an answer set."""

    expected: bool


@dataclass(frozen=True, slots=True)
class Census:
    """`@count [optimal] n`: exactly `n` distinct shown answer sets."""

    count: int
    over: Range = Range.ALL


@dataclass(frozen=True, slots=True)
class Witness:
    """`@model [optimal] { L }`, or `@optimal { L }`: some answer set shows exactly `L`."""

    literals: AnswerSet
    over: Range = Range.ALL


@dataclass(frozen=True, slots=True)
class Entails:
    """`@cautious [optimal] { L }` / `@brave [optimal] { L }`: `L` is within the consequences."""

    mode: Mode
    literals: AnswerSet
    over: Range = Range.ALL


@dataclass(frozen=True, slots=True)
class Costs:
    """`@cost { c1 c2 ... }`: the optimum is `c`, as the minimized sum of each level."""

    cost: Cost

    @property
    def over(self) -> Range:
        return Range.OPTIMAL


@dataclass(frozen=True, slots=True)
class Asks:
    """`@query A { L, ... }`: the conjunction of ground literals has answer `A`."""

    answer: Answer
    query: All


@dataclass(frozen=True, slots=True)
class Binds:
    """`@query A { q(X, ...) } = { B }`: the bindings giving answer `A` are exactly `B`."""

    answer: Answer
    pattern: Pattern
    bindings: frozenset[tuple[Symbol, ...]]


type Reading = Satisfiable | Census | Witness | Entails | Costs | Asks | Binds


@dataclass(frozen=True, slots=True)
class Claim:
    """A reading to hold under a scenario, and where it was written."""

    reading: Reading
    scenario: Scenario
    span: Span


@dataclass(frozen=True, slots=True)
class Contract:
    claims: tuple[Claim, ...]
    diagnostics: tuple[Diagnostic, ...]
