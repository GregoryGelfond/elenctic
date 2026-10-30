"""The constraint theory a search runs with: none, or clingcon, an optional dependency."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from importlib import import_module
from typing import Any, Self, override

from clingo import Control, Model
from clingo.ast import AST

from elenctic.determination import Assignment, Valuation


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


class Clingcon(Theory):
    """Integer constraints through clingcon, whose assignment of each variable a model carries."""

    def __init__(self, theory: Any) -> None:  # noqa: ANN401
        self._theory = theory

    @classmethod
    def load(cls) -> Self | None:
        """Make the theory, or `None` when clingcon is not installed."""
        try:
            return cls(import_module("clingcon").ClingconTheory())
        except ImportError:
            return None

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
            Valuation(name, value) for name, value in self._theory.assignment(model.thread_id)
        )
