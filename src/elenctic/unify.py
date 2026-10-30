"""Unification of two patterns: their most general unifier, near-linear and without recursion."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import count

from elenctic.classes import Classes
from elenctic.patterns import Pattern
from elenctic.substitution import Substitution
from elenctic.terms import Term, Variable


class Fresh:
    """A supply of variables named apart from those in use."""

    def __init__(self, used: Iterable[Variable] = ()) -> None:
        taken = {variable.name for variable in used}
        self._names: Iterator[str] = (n for i in count() if (n := f"_G{i}") not in taken)

    def variable(self) -> Variable:
        return Variable(next(self._names))


def rename_apart(pattern: Pattern, fresh: Fresh) -> Pattern:
    """Return `pattern` with each of its variables replaced by a fresh one, consistently.

    An anonymous variable is replaced by a different fresh variable at each occurrence.
    """
    renaming: dict[Variable, Variable] = {}

    def renamed(variable: Variable) -> Variable:
        if variable.anonymous:
            return fresh.variable()
        if variable not in renaming:
            renaming[variable] = fresh.variable()
        return renaming[variable]

    return pattern.renamed(renamed)


def unify_terms(left: Iterable[Term], right: Iterable[Term]) -> Substitution | None:
    """Find the most general substitution making `left` and `right` equal term for term, if any.

    This is the algorithm of Martelli and Montanari over a union-find, with the occurs check made
    once at the end instead of at every binding: near-linear in the size of the terms, whatever
    their depth. The substitution is triangular; `Substitution.apply` resolves it. Both sides
    share variables of the same name, so rename them apart first when they should not.
    """
    classes = Classes()
    pairs = [(classes.add(a), classes.add(b)) for a, b in zip(left, right, strict=True)]
    solved = all(classes.unify(a, b) for a, b in pairs)
    return classes.solution() if solved and classes.acyclic() else None


def unify(first: Pattern, second: Pattern) -> Substitution | None:
    """Find the most general unifier of two patterns, if they have one.

    The patterns must have the same signature and their variables are taken to be the same
    where they share a name.
    """
    if first.signature != second.signature:
        return None
    return unify_terms(first.arguments, second.arguments)


@dataclass(frozen=True, slots=True)
class Unifier:
    """Two patterns renamed apart, and the substitution that makes them one."""

    first: Pattern
    second: Pattern
    substitution: Substitution

    @property
    def instance(self) -> Pattern:
        """The pattern both become: the most general common instance."""
        return self.first.apply(self.substitution)


def mgu(first: Pattern, second: Pattern) -> Unifier | None:
    """Find the most general unifier of two patterns, if they have one.

    Each pattern is first renamed apart from the other, so that a variable of one does not stand
    for one of the other merely because of its name, and the unifier is over the renamed patterns.
    """
    fresh = Fresh((*first.variables, *second.variables))
    left, right = rename_apart(first, fresh), rename_apart(second, fresh)
    substitution = unify(left, right)
    return None if substitution is None else Unifier(left, right, substitution)
