"""Patterns: literals whose arguments may be terms with variables, standing for those they match."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import override

from clingo import Symbol

from elenctic.extension import Extension
from elenctic.literals import Literal, Signature
from elenctic.matching import match
from elenctic.substitution import Substitution
from elenctic.terms import Term, Variable, rename, render, variables


@dataclass(frozen=True, slots=True)
class Pattern:
    """A literal whose arguments may be terms with variables, nested to any depth."""

    name: str
    arguments: tuple[Term, ...]
    positive: bool = True

    @property
    def variables(self) -> tuple[Variable, ...]:
        """The distinct named variables, in order of first occurrence."""
        return tuple(dict.fromkeys(v for argument in self.arguments for v in variables(argument)))

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

    def match(self, literal: Literal) -> tuple[Symbol, ...] | None:
        """Return the values of `variables` that make this pattern the literal, if any."""
        if literal.signature != self.signature:
            return None
        bound = match(self.arguments, literal.arguments)
        return None if bound is None else tuple(bound[v] for v in self.variables)

    def bindings_in(self, extension: Extension) -> frozenset[tuple[Symbol, ...]]:
        """Return the values of `variables` over the literals of `extension` that match."""
        return frozenset(
            found
            for literal in extension.with_signature(self.signature)
            if (found := self.match(literal)) is not None
        )
