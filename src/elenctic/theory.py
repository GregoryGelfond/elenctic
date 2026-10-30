"""The constraint theory a search runs with: none, or clingcon, an optional dependency."""

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from typing import Protocol, Self, override

from clingo import Control, Model
from clingo.ast import AST

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
    """No theory: statements go in as written, and a model assigns nothing."""

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


class _Constraints(Protocol):
    """The part of `clingcon.ClingconTheory` that elenctic drives."""

    def register(self, control: Control, /) -> None: ...
    def rewrite_ast(self, statement: AST, add: Callable[[AST], None], /) -> None: ...
    def prepare(self, control: Control, /) -> None: ...
    def on_model(self, model: Model, /) -> None: ...
    def assignment(self, thread_id: int, /) -> Iterable[tuple[Symbol, int | float | Symbol]]: ...


class Clingcon(Theory):
    """Integer constraints through clingcon, whose assignment of each variable a model carries."""

    def __init__(self, theory: _Constraints) -> None:
        self._theory = theory

    @classmethod
    def load(cls) -> Self | None:
        """Make the theory, or `None` when clingcon is not installed."""
        try:
            from clingcon import ClingconTheory  # noqa: PLC0415
        except ImportError:
            return None
        return cls(ClingconTheory())  # type: ignore[no-untyped-call]

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
