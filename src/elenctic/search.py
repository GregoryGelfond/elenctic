"""How a search is asked, run and read: its limits, its plan, and what its models make of it."""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from math import inf
from time import monotonic
from typing import Final

from clingo import Model as ClingoModel
from clingo import SolveHandle, Symbol, SymbolType

from elenctic.determination import (
    Assignment,
    Consistent,
    Cost,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Incumbent,
    Model,
    Models,
    Optimized,
    Optimum,
    Refutation,
    Truncation,
)
from elenctic.literals import AnswerSet, Assumption, Literal, Scenario
from elenctic.theory import Theory

type Cut = Callable[[], Truncation | None]

_SLICE: Final = 0.02
_REMEMBERED: Final = 2**16


class Limit(Enum):
    """What a limit may be besides a number: none, so a search goes on until it ends."""

    UNBOUNDED = "all"


def _is_negative(limit: float | Limit) -> bool:
    return not isinstance(limit, Limit) and limit < 0


@dataclass(frozen=True, slots=True)
class Limits:
    """How far a search may go: seconds and answer sets read, each a number or `Limit.UNBOUNDED`."""

    seconds: float | Limit = Limit.UNBOUNDED
    models: int | Limit = Limit.UNBOUNDED

    def __post_init__(self) -> None:
        if any(_is_negative(limit) for limit in (self.seconds, self.models)):
            message = "a limit is never negative"
            raise ValueError(message)


UNLIMITED: Final = Limits()


def _deadline(seconds: float | Limit) -> float:
    """Return the monotonic time at which `seconds` from now are up; never, when unbounded."""
    match seconds:
        case Limit.UNBOUNDED:
            return inf
        case _:
            return monotonic() + seconds


class Interrupt:
    """A request to stop, which may be made from any thread and is heeded between models."""

    def __init__(self) -> None:
        self._pulled = threading.Event()

    def pull(self) -> None:
        self._pulled.set()

    @property
    def pulled(self) -> bool:
        return self._pulled.is_set()


@dataclass(frozen=True, slots=True)
class Request:
    """What a search is asked: the scenario its models satisfy, and how far it may go."""

    scenario: Scenario = frozenset()
    limits: Limits = UNLIMITED
    interrupt: Interrupt | None = None

    def cutter(self) -> Cut:
        """Return the check that says, as the search goes, whether it has gone far enough."""
        deadline = _deadline(self.limits.seconds)

        def cut() -> Truncation | None:
            if self.interrupt is not None and self.interrupt.pulled:
                return Truncation.INTERRUPTED
            return Truncation.BUDGET if monotonic() >= deadline else None

        return cut


@lru_cache(maxsize=_REMEMBERED)
def _literal(symbol: Symbol) -> Literal | None:
    """Read `symbol` as a classical literal; `#show` may also select numbers or strings."""
    return Literal.of(symbol) if symbol.type is SymbolType.Function and symbol.name else None


def _literals(symbols: Iterable[Symbol]) -> AnswerSet:
    """Keep the classical literals of `symbols`, each atom read once however often it recurs."""
    return frozenset(literal for s in symbols if (literal := _literal(s)) is not None)


@dataclass(frozen=True, slots=True)
class Seen:
    """A model as clingo reported it, and whether it is proven optimal (as all are, unoptimized).

    It is read into a `Model` only once it is known to be kept, which most improving models are not.
    """

    atoms: tuple[Symbol, ...]
    shown: tuple[Symbol, ...]
    assignment: Assignment
    cost: Cost
    proven: bool

    @property
    def model(self) -> Model:
        return Model(
            _literals(self.atoms), _literals(self.shown), assignment=self.assignment, cost=self.cost
        )


def seen(model: ClingoModel, theory: Theory) -> Seen:
    """Take note of a model that clingo reports."""
    return Seen(
        tuple(model.symbols(atoms=True)),
        tuple(model.symbols(shown=True)),
        theory.assignment(model),
        tuple(model.cost),
        proven=model.optimality_proven or not model.cost,
    )


@dataclass(frozen=True, slots=True)
class Run:
    """What one clingo solve call found, and how it ended; `core` only when it found nothing."""

    found: tuple[Seen, ...]
    conclusion: Exhausted | Truncation
    core: frozenset[Assumption]

    @property
    def refuted(self) -> bool:
        """Whether the whole space was searched and held nothing."""
        return self.conclusion is Exhausted.EXHAUSTED and not self.found


def _always(_: Seen) -> bool:
    return True


def proven(seen: Seen) -> bool:
    """Say whether `seen` is a model that is known to be optimal."""
    return seen.proven


@dataclass(frozen=True, slots=True)
class Plan:
    """How to run a solve: the (enum, opt) modes, what counts toward the cap on the models."""

    modes: tuple[str, str]
    counted: Callable[[Seen], bool] = _always
    cap: int | Limit = Limit.UNBOUNDED

    def allows(self, counted: int) -> bool:
        """Say whether `counted` models are within the cap."""
        return isinstance(self.cap, Limit) or counted <= self.cap


ENUMERATION: Final = ("auto", "ignore")
OPTIMIZATION: Final = ("auto", "optN")


def _await(handle: SolveHandle, cut: Cut) -> Truncation | None:
    """Wait for a model or the end, cancelling the search if it is cut first."""
    while (truncation := cut()) is None:
        if handle.wait(_SLICE):
            return None
    handle.cancel()
    return truncation


def drain(
    handle: SolveHandle, plan: Plan, cut: Cut, read: Callable[[ClingoModel], Seen]
) -> tuple[list[Seen], Exhausted | Truncation]:
    """Take models until the end, the cut, or one more counted model than the cap of `plan`."""
    found: list[Seen] = []
    counted = 0
    handle.resume()
    while (truncation := _await(handle, cut)) is None:
        if (model := handle.model()) is None:
            return found, Exhausted.EXHAUSTED if handle.get().exhausted else Truncation.TARGET
        found.append(read(model))
        counted += plan.counted(found[-1])
        if not plan.allows(counted):
            handle.cancel()
            return found[:-1], Truncation.TARGET
        handle.resume()
    return found, truncation


def decide[E](
    run: Run, refutation: Refutation | None, evidence: Callable[[list[Seen]], E]
) -> Determination[E]:
    """Read a run as a determination: models make it consistent, an exhausted none inconsistent."""
    if run.found:
        return Consistent(evidence(list(run.found)), run.conclusion)
    match run.conclusion:
        case Exhausted.EXHAUSTED if refutation is not None:
            return Inconsistent(refutation)
        case Truncation() as truncation:
            return Inconclusive(truncation)
        case _:
            message = "an exhausted search that found nothing is refuted"
            raise ValueError(message)


def models(found: list[Seen]) -> Models:
    """Present the models found: the first, and those after it."""
    each = [seen.model for seen in found]
    return Models(each[0], tuple(each[1:]))


def optimized(found: list[Seen]) -> Optimized:
    """Present the optimum if one is proven, else the best model so far."""
    optimal = [seen for seen in found if seen.proven]
    if optimal:
        return Optimum(optimal[0].cost, models(optimal))
    return Incumbent(found[-1].model)
