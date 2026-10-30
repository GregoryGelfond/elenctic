"""What a solve can come to: consistent, inconsistent or inconclusive, and how its search ended."""

from dataclasses import dataclass
from enum import StrEnum

from aspnext.literals import AnswerSet, Assumption


class Exhausted(StrEnum):
    """The search covered every stable model under the request."""

    EXHAUSTED = "exhausted"


class Truncation(StrEnum):
    """The search was cut short, and by what."""

    TARGET = "target"
    BUDGET = "budget"
    INTERRUPTED = "interrupted"


type Conclusion = Exhausted | Truncation


@dataclass(frozen=True, slots=True)
class Model:
    """A stable model, as every atom of it and as the atoms `#show` selects."""

    atoms: AnswerSet
    shown: AnswerSet


@dataclass(frozen=True, slots=True)
class Models:
    """At least one model, in the order the solver found them."""

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
    """The atoms true in every (cautious) or some (brave) stable model, among those shown."""

    mode: Mode
    literals: AnswerSet


@dataclass(frozen=True, slots=True)
class Refutation:
    """Assumptions that no stable model satisfies; empty when the program has none at all."""

    core: frozenset[Assumption]


@dataclass(frozen=True, slots=True)
class Consistent[E]:
    """A stable model exists, and `evidence` is what the search found, ended as `conclusion`."""

    evidence: E
    conclusion: Conclusion


@dataclass(frozen=True, slots=True)
class Inconsistent:
    """The search ended having covered everything, and no stable model satisfies the request."""

    refutation: Refutation


@dataclass(frozen=True, slots=True)
class Inconclusive:
    """The search was cut short before it decided."""

    truncation: Truncation


type Determination[E] = Consistent[E] | Inconsistent | Inconclusive


@dataclass(frozen=True, slots=True)
class WorldView:
    """The answer sets of a program, all of them: only an exhausted search yields one."""

    members: frozenset[AnswerSet]

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
        return frozenset().union(*self.members)


def world_view(found: Consistent[Models], *, shown: bool = True) -> WorldView | Truncation:
    """Close a consistent search over models into its world view, or say what left it open."""
    match found.conclusion:
        case Exhausted.EXHAUSTED:
            return WorldView(frozenset(m.shown if shown else m.atoms for m in found.evidence.all))
        case Truncation() as cut:
            return cut
