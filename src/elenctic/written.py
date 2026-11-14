"""Write a ground rule instance as the explanation shows it, with its variables' values in."""

from collections.abc import Mapping
from typing import Final

from elenctic.clauses import Form, Instance, Kind, ground_text
from elenctic.instances import Instances
from elenctic.literals import Symbol, integer

_NOT: Final = "not "


def negated(negations: int, text: str) -> str:
    """Write a literal under its `not`s."""
    return _NOT * negations + text


def values_of(instance: Instance) -> dict[str, Symbol]:
    """Map each variable of an instance's clause to its value."""
    return dict(zip(instance.clause.variables, instance.values, strict=True))


class Writer:
    """The writer of the instances of one program's rules."""

    def __init__(self, instances: Instances) -> None:
        self._instances = instances

    def text(self, instance: Instance) -> str:
        """Write the ground rule instance, with the values of its variables filled in."""
        clause = instance.clause
        env = values_of(instance)
        body = [
            negated(part.negations, str(slot))
            if part.kind is Kind.ATOM
            else ground_text(part.node, env)
            for part, slot in zip(clause.body, instance.body, strict=True)
        ]
        tail = f" :- {', '.join(body)}." if body else "."
        match clause.form:
            case Form.CHOICE:
                return self._choice_text(instance, env) + tail
            case Form.DISJUNCTION:
                more = "; …" if len(self._instances.group(instance)) > 1 else ""
                return f"{self._element(instance, env)}{more}" + tail
            case _:
                return f"{instance.head}" + tail

    def _element(self, instance: Instance, env: Mapping[str, Symbol]) -> str:
        clause = instance.clause
        conditions = [
            negated(part.negations, str(slot))
            if part.kind is Kind.ATOM
            else ground_text(part.node, env)
            for part, slot in zip(clause.condition, instance.condition, strict=True)
        ]
        return f"{instance.head}" + (f": {', '.join(conditions)}" if conditions else "")

    def _choice_text(self, instance: Instance, env: Mapping[str, Symbol]) -> str:
        more = "; …" if len(self._instances.group(instance)) > 1 else ""
        bounds = [b for side in instance.bounds for b in side.arguments]
        left = right = ""
        for guard, bound in zip(instance.clause.bounds, bounds, strict=True):
            if guard.left:
                left = f"{bound} {guard.written} "
            else:
                right = f" {guard.written} {bound}"
        return f"{left}{{ {self._element(instance, env)}{more} }}{right}"


_LOWER: Final = {"=": 0, ">=": 0, ">": 1}
_UPPER: Final = {"=": 0, "<=": 0, "<": -1}


def choice_bounds(instance: Instance) -> tuple[int | None, int | None]:
    """Give the fewest and most atoms a choice instance may choose; `None` where unbounded."""
    lower: int | None = None
    upper: int | None = None
    bounds = [b for side in instance.bounds for b in side.arguments]
    for guard, bound in zip(instance.clause.bounds, bounds, strict=True):
        number = integer(bound)
        if number is None:
            continue
        if guard.operator in _LOWER:
            lower = number + _LOWER[guard.operator]
        if guard.operator in _UPPER:
            upper = number + _UPPER[guard.operator]
    return lower, upper
