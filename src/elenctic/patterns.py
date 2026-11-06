"""Patterns: literals whose arguments may be terms with variables, standing for their instances."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from clingo import Symbol

from elenctic.literals import Literal, Signature
from elenctic.substitution import Substitution
from elenctic.terms import Term, Variable, leaves, rename, render, variables


@dataclass(frozen=True, slots=True)
class Pattern:
    """A literal whose arguments may be terms with variables, nested to any depth."""

    name: str
    arguments: tuple[Term, ...]
    positive: bool = True

    @classmethod
    def of(cls, literal: Literal) -> Pattern:
        """Return the pattern with no variables that is `literal`."""
        return cls(literal.name, literal.arguments, literal.positive)

    @property
    def variables(self) -> tuple[Variable, ...]:
        """The distinct named variables, in order of first occurrence."""
        return tuple(dict.fromkeys(v for argument in self.arguments for v in variables(argument)))

    @property
    def anonymous(self) -> bool:
        """Say whether some argument has an anonymous variable, `_`, beneath it."""
        return any(
            isinstance(leaf, Variable) and leaf.anonymous
            for argument in self.arguments
            for leaf in leaves(argument)
        )

    @property
    def contrary(self) -> Pattern:
        return Pattern(self.name, self.arguments, not self.positive)

    @property
    def signature(self) -> Signature:
        return Signature(self.name, len(self.arguments), self.positive)

    @override
    def __str__(self) -> str:
        sign = "" if self.positive else "-"
        arguments = ",".join(render(argument) for argument in self.arguments)
        return f"{sign}{self.name}({arguments})" if arguments else f"{sign}{self.name}"

    def as_literal(self) -> Literal | None:
        """Return the literal this pattern is, if it has no variables."""
        symbols = tuple(a for a in self.arguments if isinstance(a, Symbol))
        return (
            Literal(self.name, symbols, self.positive)
            if len(symbols) == len(self.arguments)
            else None
        )

    def apply(self, substitution: Substitution) -> Pattern:
        """Return this pattern with the variables `substitution` binds replaced."""
        return Pattern(
            self.name, tuple(substitution.apply(a) for a in self.arguments), self.positive
        )

    def renamed(self, renaming: Callable[[Variable], Variable]) -> Pattern:
        """Return this pattern with each variable replaced by what `renaming` makes of it."""
        return Pattern(self.name, tuple(rename(a, renaming) for a in self.arguments), self.positive)
