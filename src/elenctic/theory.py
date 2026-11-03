"""The constraint theory a search runs with: none, or clingcon, an optional dependency."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Protocol, Self, override, runtime_checkable

import clingo
from clingo import Control, Model
from clingo.ast import AST

from elenctic.about import Solvers
from elenctic.determination import Assignment, Valuation
from elenctic.literals import Symbol


class Theory(ABC):
    """What a theory does to a program and to a search: the steps clingcon's API takes in order."""

    @abstractmethod
    def register(self, control: Control) -> None:
        """Attach the theory's propagator to `control`, before anything is added."""

    @abstractmethod
    def rewrite(self, statement: AST, add: Callable[[AST], None]) -> None:
        """Add `statement` as the theory needs it: clingcon translates its theory atoms."""

    @abstractmethod
    def prepare(self, control: Control) -> None:
        """Ready the theory once the program is grounded."""

    @abstractmethod
    def assignment(self, model: Model) -> Assignment:
        """Read what the theory assigns in `model`, which clingo is yielding now."""


class Plain(Theory):
    """No theory: statements go in as written, and an answer set assigns nothing."""

    @override
    def register(self, control: Control) -> None:
        pass

    @override
    def rewrite(self, statement: AST, add: Callable[[AST], None]) -> None:
        add(statement)

    @override
    def prepare(self, control: Control) -> None:
        pass

    @override
    def assignment(self, model: Model) -> Assignment:
        return frozenset()


@runtime_checkable
class _Constraints(Protocol):
    """The part of `clingcon.ClingconTheory` that elenctic drives."""

    def register(self, control: Control, /) -> None: ...
    def rewrite_ast(self, statement: AST, add: Callable[[AST], None], /) -> None: ...
    def prepare(self, control: Control, /) -> None: ...
    def on_model(self, model: Model, /) -> None: ...
    def assignment(self, thread_id: int, /) -> Iterable[tuple[Symbol, int | float | Symbol]]: ...
    def version(self) -> tuple[int, int, int]: ...


class Clingcon(Theory):
    """Integer constraints through clingcon, whose assignment each answer set carries."""

    def __init__(self, theory: _Constraints) -> None:
        self._theory = theory

    @classmethod
    def load(cls) -> Self | None:
        """Make the theory, or `None` when clingcon is not installed."""
        try:
            # Imported here: clingcon is an optional extra, and its absence is an answer.
            from clingcon import ClingconTheory  # noqa: PLC0415
        except ImportError:
            return None
        make: Callable[[], _Constraints] = ClingconTheory
        return cls(make())

    @property
    def version(self) -> str:
        """The version of the clingcon that is loaded, as its own library reports it."""
        return ".".join(str(part) for part in self._theory.version())

    @override
    def register(self, control: Control) -> None:
        self._theory.register(control)

    @override
    def rewrite(self, statement: AST, add: Callable[[AST], None]) -> None:
        self._theory.rewrite_ast(statement, add)

    @override
    def prepare(self, control: Control) -> None:
        self._theory.prepare(control)

    @override
    def assignment(self, model: Model) -> Assignment:
        self._theory.on_model(model)
        return frozenset(
            Valuation(name, value)
            for name, value in self._theory.assignment(model.thread_id)
            if isinstance(value, int)
        )


def loaded_solvers() -> Solvers:
    """Read the versions of clingo and clingcon as loaded; clingcon is `None` when not installed."""
    theory = Clingcon.load()
    return Solvers(clingo.__version__, None if theory is None else theory.version)
