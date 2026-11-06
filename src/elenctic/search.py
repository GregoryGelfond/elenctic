"""How a search is asked, run and read: its limits, its plan, and its answer sets."""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from math import inf
from time import monotonic
from typing import Final, Protocol, runtime_checkable

from clingo import Model as ClingoModel
from clingo import SolveResult, Symbol, SymbolType

from elenctic.determination import (
    AnswerSet,
    AnswerSets,
    Assignment,
    Consistent,
    Cost,
    Determination,
    Exhausted,
    Inconclusive,
    Inconsistent,
    Incumbent,
    Optimized,
    Optimum,
    Refutation,
    Truncation,
)
from elenctic.literals import Assumption, Atoms, Literal, Scenario
from elenctic.theory import Theory

type Cut = Callable[[], Truncation | None]

_SLICE: Final = 0.02
_REMEMBERED: Final = 2**16


class Limit(Enum):
    """A limit besides a number: none, so a search goes on until it ends."""

    UNBOUNDED = "all"


def _is_negative(limit: float | Limit) -> bool:
    return not isinstance(limit, Limit) and limit < 0


@dataclass(frozen=True, slots=True)
class Limits:
    """How far a search may go: seconds and answer sets, each a number or `Limit.UNBOUNDED`."""

    max_seconds: float | Limit = Limit.UNBOUNDED
    max_answer_sets: int | Limit = Limit.UNBOUNDED

    def __post_init__(self) -> None:
        if any(_is_negative(limit) for limit in (self.max_seconds, self.max_answer_sets)):
            message = "a limit is never negative"
            raise ValueError(message)


def _deadline(seconds: float | Limit) -> float:
    """Return the monotonic time at which `seconds` from now are up; never, when unbounded."""
    match seconds:
        case Limit.UNBOUNDED:
            return inf
        case _:
            return monotonic() + seconds


class Interrupt:
    """A request to stop, which may be made from any thread and is heeded between answer sets."""

    def __init__(self) -> None:
        self._pulled = threading.Event()

    def pull(self) -> None:
        self._pulled.set()

    @property
    def pulled(self) -> bool:
        return self._pulled.is_set()


@dataclass(frozen=True, slots=True)
class Request:
    """A search request: the scenario its answer sets satisfy, and how far it may go."""

    scenario: Scenario = frozenset()
    limits: Limits = field(default_factory=Limits)
    interrupt: Interrupt | None = None

    def cutter(self) -> Cut:
        """Return the check that says, as the search goes, whether it has gone far enough."""
        deadline = _deadline(self.limits.max_seconds)

        def cut() -> Truncation | None:
            if self.interrupt is not None and self.interrupt.pulled:
                return Truncation.INTERRUPTED
            return Truncation.MAX_SECONDS if monotonic() >= deadline else None

        return cut


@lru_cache(maxsize=_REMEMBERED)
def _literal(symbol: Symbol) -> Literal | None:
    """Read `symbol` as a classical literal; `#show` may also select numbers or strings."""
    return Literal.of(symbol) if symbol.type is SymbolType.Function and symbol.name else None


def _literals(symbols: Iterable[Symbol]) -> Atoms:
    """Keep the classical literals of `symbols`, each atom read once however often it recurs."""
    return frozenset(literal for s in symbols if (literal := _literal(s)) is not None)


@dataclass(frozen=True, slots=True)
class Seen:
    """An answer set as clingo reported it, and whether it is proven optimal (all are, unoptimized).

    It is read into an `AnswerSet` only once it is kept, which most improving ones are not.
    """

    atoms: tuple[Symbol, ...]
    shown: tuple[Symbol, ...]
    assignment: Assignment
    cost: Cost
    proven: bool

    @property
    def answer_set(self) -> AnswerSet:
        return AnswerSet(
            _literals(self.atoms), _literals(self.shown), assignment=self.assignment, cost=self.cost
        )


def seen(answer_set: ClingoModel, theory: Theory) -> Seen:
    """Take note of an answer set that clingo reports."""
    return Seen(
        tuple(answer_set.symbols(atoms=True)),
        tuple(answer_set.symbols(shown=True)),
        theory.assignment(answer_set),
        tuple(answer_set.cost),
        proven=answer_set.optimality_proven or not answer_set.cost,
    )


@dataclass(frozen=True, slots=True)
class Run:
    """The result of one clingo solve call, and how it ended; `core` only when it found nothing."""

    found: tuple[Seen, ...]
    conclusion: Exhausted | Truncation
    core: frozenset[Assumption]

    @property
    def refuted(self) -> bool:
        """Say whether the whole space was searched and held nothing."""
        return self.conclusion is Exhausted.EXHAUSTED and not self.found


def _always(_: Seen) -> bool:
    return True


def proven(seen: Seen) -> bool:
    """Say whether `seen` is an answer set that is known to be optimal."""
    return seen.proven


@dataclass(frozen=True, slots=True)
class Plan:
    """How to run a solve: the (enum, opt) modes, how many answer sets it may count."""

    modes: tuple[str, str]
    counted: Callable[[Seen], bool] = _always
    max_answer_sets: int | Limit = Limit.UNBOUNDED
    project: bool = False
    """Enumerate distinct `#show` projections when the claims read only shown identities."""
    enough: Callable[[list[Seen]], bool] | None = None
    """Stop once every claim the group cares about is decided from `found` (existential groups)."""

    def allows(self, counted: int) -> bool:
        """Say whether `counted` answer sets are within the most allowed."""
        return isinstance(self.max_answer_sets, Limit) or counted <= self.max_answer_sets


ENUMERATION: Final = ("auto", "ignore")
OPTIMIZATION: Final = ("auto", "optN")


@runtime_checkable
class _Handle(Protocol):
    """The part of `clingo.SolveHandle` that a search drives."""

    def resume(self) -> None: ...
    def wait(self, _: float, /) -> bool: ...
    def cancel(self) -> None: ...
    def model(self) -> ClingoModel | None: ...
    def get(self) -> SolveResult: ...


def _await(handle: _Handle, cut: Cut) -> Truncation | None:
    """Wait for an answer set or the end, canceling the search if it is cut first."""
    while (truncation := cut()) is None:
        if handle.wait(_SLICE):
            return None
    handle.cancel()
    return truncation


def drain(
    handle: _Handle, plan: Plan, cut: Cut, read: Callable[[ClingoModel], Seen]
) -> tuple[list[Seen], Exhausted | Truncation]:
    """Take answer sets until the end, the cut, or one more than `plan` allows."""
    found: list[Seen] = []
    counted = 0
    handle.resume()
    while (truncation := _await(handle, cut)) is None:
        if (model := handle.model()) is None:
            return (
                found,
                Exhausted.EXHAUSTED if handle.get().exhausted else Truncation.MAX_ANSWER_SETS,
            )
        found.append(read(model))
        counted += plan.counted(found[-1])
        if not plan.allows(counted):
            handle.cancel()
            return found[:-1], Truncation.MAX_ANSWER_SETS
        if plan.enough is not None and plan.enough(found):
            handle.cancel()
            return found, Exhausted.EXHAUSTED
        handle.resume()
    return found, truncation


def decide[E](
    run: Run, refutation: Refutation | None, evidence: Callable[[list[Seen]], E]
) -> Determination[E]:
    """Read a run as a determination: answer sets make it consistent, an exhausted none not."""
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


def answer_sets(found: list[Seen]) -> AnswerSets:
    """Present the answer sets found: the first, and those after it."""
    each = [seen.answer_set for seen in found]
    return AnswerSets(each[0], tuple(each[1:]))


def optimized(found: list[Seen]) -> Optimized:
    """Present the optimum if one is proven, else the best answer set so far."""
    optimal = [seen for seen in found if seen.proven]
    if optimal:
        return Optimum(optimal[0].cost, answer_sets(optimal))
    return Incumbent(found[-1].answer_set)
