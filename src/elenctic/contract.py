"""The contract: the claims a program is held to, as a vocabulary of readings."""

from dataclasses import dataclass
from enum import StrEnum

from elenctic.determination import Assignment, Cost, Mode, Model, Range
from elenctic.literals import AnswerSet, Pattern, Scenario, Symbol
from elenctic.query import All, Answer
from elenctic.spans import Diagnostic, Span


class Solver(StrEnum):
    """What a contract is checked with: clingo alone, or clingo with the clingcon theory."""

    CLINGO = "clingo"
    CLINGCON = "clingcon"


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
    """`@model [optimal] { L } [where { A }]`, or `@optimal { L }`.

    Some answer set shows exactly `L` and, given `A`, assigns at least `A`.
    """

    literals: AnswerSet
    over: Range = Range.ALL
    assignment: Assignment = frozenset()

    def upheld_by(self, model: Model) -> bool:
        return model.shown == self.literals and self.assignment <= model.assignment


@dataclass(frozen=True, slots=True)
class Assigns:
    """`@assign [optimal] { A }`: some answer set has a theory assignment containing `A`."""

    assignment: Assignment
    over: Range = Range.ALL

    def upheld_by(self, model: Model) -> bool:
        return self.assignment <= model.assignment


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


type Reading = Satisfiable | Census | Witness | Assigns | Entails | Costs | Asks | Binds


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
    solver: Solver = Solver.CLINGO


def over(reading: Reading) -> Range:
    """Name the model set a claim is about: only the optimal-set claims say otherwise."""
    if isinstance(reading, Census | Witness | Assigns | Entails | Costs):
        return reading.over
    return Range.ALL


def denies_answer_sets(reading: Reading) -> bool:
    """Say whether the claim is that there are no answer sets: `@count 0`, of either set."""
    return isinstance(reading, Census) and reading.count == 0
