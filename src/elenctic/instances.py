"""The rule instances that could derive each atom, read from the grounded relaxation."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from clingo import Function, Number, Symbol, Tuple_

from elenctic.clauses import Instance, Kind, Weak, tuple_text
from elenctic.literals import integer, is_function
from elenctic.relaxation import Reading


def _arguments(symbol: Symbol) -> list[Symbol]:
    return list(symbol.arguments)


@dataclass(frozen=True, slots=True)
class Payment:
    """A weak-constraint instance an answer set pays."""

    weak: Weak
    values: tuple[Symbol, ...]
    weight: int
    priority: int
    terms: tuple[Symbol, ...]


@dataclass(frozen=True, slots=True)
class Element:
    """An element an aggregate could count: its index, terms, and what its condition grounds to."""

    index: int
    terms: tuple[Symbol, ...]
    condition: tuple[Symbol, ...]


@dataclass(frozen=True, slots=True)
class Instances:
    """Every instance the relaxation found, by the atom it derives, and the aggregates' elements."""

    reading: Reading
    by_head: Mapping[Symbol, tuple[Instance, ...]]
    elements: Mapping[tuple[int, tuple[Symbol, ...], int], tuple[Element, ...]]
    groups: Mapping[tuple[int, tuple[Symbol, ...]], tuple[Instance, ...]]

    def candidates(self, atom: Symbol) -> tuple[Instance, ...]:
        """Return the instances that could derive an atom, in the order their rules are written."""
        return self.by_head.get(atom, ())

    def binding(self) -> list[str]:
        """Write the facts that bind the theory-atom rules to each instance whose body has one."""
        pieces = {
            c.piece for c in self.reading.clauses if any(p.kind is Kind.THEORY for p in c.body)
        }
        bound = {
            (instance.clause.piece, instance.shared)
            for instances in self.by_head.values()
            for instance in instances
            if instance.clause.piece in pieces
        }
        return [
            f"{self.reading.bind}({piece},{tuple_text(str(v) for v in values)})."
            for piece, values in sorted(bound, key=str)
        ]

    def theory_holds(self, atoms: frozenset[Symbol], instance: Instance, at: int) -> bool:
        """Say whether the theory atom at `at` of an instance's body holds among `atoms`."""
        recorded = Function(
            self.reading.theory,
            [Number(instance.clause.piece), Tuple_(list(instance.shared)), Number(at)],
        )
        return recorded in atoms

    def paid(self, atoms: Iterable[Symbol]) -> frozenset[Payment]:
        """Read the weak-constraint instances an answer set pays from its recorded atoms."""
        found: set[Payment] = set()
        for atom in atoms:
            if not is_function(atom) or atom.name != self.reading.paid:
                continue
            number, values, weight_term, priority_term, terms = _arguments(atom)
            weight, priority = integer(weight_term), integer(priority_term)
            if weight is not None and priority is not None:
                weak = self.reading.weak[number.number]
                found.add(
                    Payment(weak, tuple(values.arguments), weight, priority, tuple(terms.arguments))
                )
        return frozenset(found)

    def group(self, instance: Instance) -> tuple[Instance, ...]:
        """Return the instances of the same ground choice: one rule, the same values of its own."""
        return self.groups.get((instance.clause.piece, instance.shared), ())


type _Key = tuple[int, tuple[Symbol, ...], int]


def _recorded(reading: Reading, atom: Symbol) -> Instance | tuple[_Key, Element] | None:
    """Read the instance, or the element with its key, that one atom of the relaxation records."""
    if not is_function(atom):
        return None
    if atom.name == reading.rule:
        number, values, head, body, condition, bounds = _arguments(atom)
        return Instance(
            reading.clauses[number.number],
            tuple(values.arguments),
            head,
            tuple(body.arguments),
            tuple(condition.arguments),
            tuple(bounds.arguments),
        )
    if atom.name == reading.element:
        piece, shared, at, index, terms, condition = _arguments(atom)
        key = (piece.number, tuple(shared.arguments), at.number)
        return key, Element(index.number, tuple(terms.arguments), tuple(condition.arguments))
    return None


def instances(reading: Reading, atoms: Iterable[Symbol]) -> Instances:
    """Read the instances out of the atoms of the grounded relaxation."""
    by_head: dict[Symbol, list[Instance]] = {}
    elements: dict[_Key, list[Element]] = {}
    groups: dict[tuple[int, tuple[Symbol, ...]], list[Instance]] = {}
    for atom in atoms:
        match _recorded(reading, atom):
            case Instance() as instance:
                by_head.setdefault(instance.head, []).append(instance)
                groups.setdefault((instance.clause.piece, instance.shared), []).append(instance)
            case (key, element):
                elements.setdefault(key, []).append(element)
            case None:
                pass
    return Instances(
        reading,
        {head: tuple(sorted(found, key=order)) for head, found in by_head.items()},
        {key: tuple(sorted(found, key=str)) for key, found in elements.items()},
        {key: tuple(sorted(found, key=order)) for key, found in groups.items()},
    )


def order(instance: Instance) -> tuple[int, int, str]:
    """Order instances as their rules are written, then by the values of their variables."""
    return instance.clause.rule.statement, instance.clause.number, str(instance.values)
