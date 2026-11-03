"""What a solve can come to: consistent, inconsistent or inconclusive, and how its search ended."""

from dataclasses import dataclass
from enum import StrEnum

from elenctic.literals import AnswerSet, Assumption, Literal, Symbol


class Exhausted(StrEnum):
    """The search covered every answer set under the request."""

    EXHAUSTED = "exhausted"


class Truncation(StrEnum):
    """The search was cut short, and by what."""

    TARGET = "target"
    BUDGET = "budget"
    INTERRUPTED = "interrupted"


type Conclusion = Exhausted | Truncation


class Range(StrEnum):
    """The answer set set a value ranges over: every answer set, or those optimal."""

    ALL = "all"
    OPTIMAL = "optimal"


type Cost = tuple[int, ...]
"""The value of each objective level, highest priority first, as the minimized sum clingo reports:
`#maximize { w }` is `#minimize { -w }`, so a maximized level is negated."""


@dataclass(frozen=True, slots=True, order=True)
class Valuation:
    """A theory variable and the integer an answer set gives it."""

    variable: Symbol
    value: int


type Assignment = frozenset[Valuation]
"""What a constraint theory assigns in an answer set, kept apart from its literal atoms."""


@dataclass(frozen=True, slots=True)
class Model:
    """An answer set: every atom of it, the atoms `#show` selects, its theory assignment and cost.

    `assignment` is empty without a theory. `cost` is empty unless the search optimized: clingo
    reports no cost when it ignores the objective, so a plain enumeration carries none.
    """

    atoms: AnswerSet
    shown: AnswerSet
    assignment: Assignment = frozenset()
    cost: Cost = ()

    @property
    def identity(self) -> tuple[AnswerSet, Assignment]:
        """What tells answer sets apart: the atoms shown and the assignment, not the hidden ones."""
        return self.shown, self.assignment


@dataclass(frozen=True, slots=True)
class Models:
    """At least one answer set, in the order the solver found them."""

    first: Model
    rest: tuple[Model, ...] = ()

    @property
    def all(self) -> tuple[Model, ...]:
        return (self.first, *self.rest)


class Mode(StrEnum):
    CAUTIOUS = "cautious"
    BRAVE = "brave"


@dataclass(frozen=True, slots=True)
class Consequences:
    """The atoms true in every (cautious) or some (brave) answer set, among those shown."""

    mode: Mode
    literals: AnswerSet
    over: Range = Range.ALL


@dataclass(frozen=True, slots=True)
class These:
    """These assumptions, no fewer when `minimal`, admit no answer set."""

    core: frozenset[Assumption]
    minimal: bool = True


@dataclass(frozen=True, slots=True)
class NotThese:
    """The program has no answer set whatever is assumed, and something is assumed."""


@dataclass(frozen=True, slots=True)
class NoAssumptions:
    """The program has no answer set, and nothing is assumed."""


type Refutation = These | NotThese | NoAssumptions


@dataclass(frozen=True, slots=True)
class Consistent[E]:
    """An answer set exists, and `evidence` is what the search found, ended as `conclusion`."""

    evidence: E
    conclusion: Conclusion


@dataclass(frozen=True, slots=True)
class Inconsistent:
    """The search ended having covered everything, and no answer set satisfies the request."""

    refutation: Refutation


@dataclass(frozen=True, slots=True)
class Inconclusive:
    """The search was cut short before it decided."""

    truncation: Truncation


type Determination[E] = Consistent[E] | Inconsistent | Inconclusive


@dataclass(frozen=True, slots=True)
class Optimum:
    """A proven optimum: its cost, and the optimal answer sets found (all, if exhausted)."""

    cost: Cost
    models: Models


@dataclass(frozen=True, slots=True)
class Incumbent:
    """The best answer set found before the search was cut: not proven optimal."""

    model: Model


type Optimized = Optimum | Incumbent


@dataclass(frozen=True, slots=True)
class WorldView:
    """The answer sets of a program, all of them: only an exhausted search yields one."""

    members: frozenset[AnswerSet]
    over: Range = Range.ALL

    def __post_init__(self) -> None:
        if not self.members:
            message = "a world view has no answer set to be empty of"
            raise ValueError(message)

    @property
    def cautious(self) -> AnswerSet:
        first, *rest = self.members
        return first.intersection(*rest)

    @property
    def brave(self) -> AnswerSet:
        return frozenset[Literal]().union(*self.members)


def world_view(found: Consistent[Models], *, shown: bool = True) -> WorldView | Truncation:
    """Close a consistent search over answer sets into its world view, or say what left it open."""
    match found.conclusion:
        case Exhausted.EXHAUSTED:
            return WorldView(frozenset(m.shown if shown else m.atoms for m in found.evidence.all))
        case Truncation() as cut:
            return cut


def optimal_view(found: Consistent[Optimized]) -> WorldView | Truncation:
    """Close a proven optimum into the world view of its optimal answer sets, or say what cut it."""
    match found.evidence, found.conclusion:
        case Optimum(_, models), Exhausted.EXHAUSTED:
            return WorldView(frozenset(m.shown for m in models.all), Range.OPTIMAL)
        case _, Truncation() as cut:
            return cut
        case _:
            message = "a search that exhausted its space has proven its optimum"
            raise ValueError(message)
