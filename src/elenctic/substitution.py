"""Substitutions: what variables stand for once patterns have been matched or unified."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import override

from elenctic.terms import Term, Variable, substitute_with


@dataclass(frozen=True, slots=True)
class Substitution:
    """What some variables stand for, as the matching or unifying of patterns found.

    It is *triangular*: a binding may mention variables that are bound in turn (`X` to `f(Y)` with
    `Y` bound to `a`), which is what lets a unifier produce it in near-linear space, where the
    fully resolved form can be exponentially larger. `apply` resolves, and the empty substitution
    is the one that binds nothing.
    """

    bindings: Mapping[Variable, Term] = field(default_factory=dict[Variable, Term])

    def get(self, variable: Variable) -> Term | None:
        """Return the term `variable` is bound to, as it was bound, or `None` if it is free."""
        return self.bindings.get(variable)

    def apply(self, term: Term) -> Term:
        """Return `term` with every bound variable replaced, resolving through the bindings."""
        return substitute_with(term, self.get)

    def __or__(self, other: Substitution) -> Substitution:
        """Combine two substitutions over different variables."""
        return Substitution({**self.bindings, **other.bindings})

    @override
    def __str__(self) -> str:
        return "{" + ", ".join(f"{k.name}={v}" for k, v in sorted(self.bindings.items())) + "}"
