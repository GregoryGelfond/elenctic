"""What holds in one answer set: atoms, the literals of an instance's body, its aggregates."""

import operator
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from elenctic.clauses import Instance, Kind, Part
from elenctic.instances import Element, Instances
from elenctic.literals import Number, Symbol, integer

_COMPARE: Final[Mapping[str, Callable[[Symbol, Symbol], bool]]] = {
    "=": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def positive_atom(part: Part) -> bool:
    """Say whether a literal is an atom without `not`."""
    return part.kind is Kind.ATOM and part.negations == 0


@dataclass(frozen=True, slots=True)
class Value:
    """What an instance's aggregate comes to: the elements it counts, its value, if it holds."""

    counted: tuple[Element, ...]
    missing: tuple[Element, ...]
    value: int
    holds: bool
    guard: str


class Holding:
    """What holds among the atoms of one answer set, with the atoms the session records."""

    def __init__(self, instances: Instances, atoms: frozenset[Symbol]) -> None:
        self._instances = instances
        self._atoms = atoms

    def holds(self, atom: Symbol) -> bool:
        """Say whether an atom is in the answer set."""
        return atom in self._atoms

    def part_holds(self, instance: Instance, at: int, part: Part, slot: Symbol) -> bool:
        """Say whether the body literal at `at` of an instance holds."""
        match part.kind:
            case Kind.ATOM:
                found = self.holds(slot)
                return found if part.negations % 2 == 0 else not found
            case Kind.AGGREGATE:
                held = self.value(instance, at, part).holds
                return held if part.negations % 2 == 0 else not held
            case Kind.THEORY:
                held = self._instances.theory_holds(self._atoms, instance, at)
                return held if part.negations % 2 == 0 else not held
            case _:
                return True

    def condition_holds(self, part: Part, slot: Symbol) -> bool:
        """Say whether a literal of a condition holds; a comparison held when it was grounded."""
        if part.kind is not Kind.ATOM:
            return True
        found = self.holds(slot)
        return found if part.negations % 2 == 0 else not found

    def value(self, instance: Instance, at: int, part: Part) -> Value:
        """Count the aggregate at `at` of an instance's body, and compare it with its guards."""
        key = (instance.clause.piece, instance.shared, at)
        elements = self._instances.elements.get(key, ())
        counted = tuple(
            e
            for e in elements
            if all(
                self.condition_holds(c, s)
                for c, s in zip(part.elements[e.index], e.condition, strict=True)
            )
        )
        missing = tuple(e for e in elements if e not in counted)
        value = _aggregate_value(part.function, counted)
        bounds = [b for side in instance.body[at].arguments for b in side.arguments]
        holds = all(
            _COMPARE[guard.operator](Number(value), bound)
            for guard, bound in zip(part.guards, bounds, strict=True)
        )
        guard = ", ".join(f"{g.operator} {b}" for g, b in zip(part.guards, bounds, strict=True))
        return Value(counted, missing, value, holds, guard)

    def counted_atoms(self, instance: Instance, at: int, part: Part) -> list[Symbol]:
        """Name the positive atoms of the conditions of the elements an aggregate counts."""
        found = self.value(instance, at, part)
        return [
            slot
            for element in found.counted
            for condition, slot in zip(part.elements[element.index], element.condition, strict=True)
            if positive_atom(condition)
        ]


def _aggregate_value(function: str, counted: Sequence[Element]) -> int:
    tuples = {element.terms for element in counted}
    if function == "count":
        return len(tuples)
    weights = [w for t in tuples if t and (w := integer(t[0])) is not None]
    return sum(w for w in weights if function == "sum" or w > 0)
