"""Why atoms hold or not in an answer set: support for those that hold, blocked rules for the rest.

An atom that holds gets one rule instance whose positive body atoms were supported before it, so the
support is well founded. An atom that does not hold gets every instance that could derive it, each
with the first literal of its body, in body order, that does not hold there.
"""

import heapq
import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from elenctic.clauses import Form, Instance, Kind, Part, atom_of, ground_text
from elenctic.determination import Valuation
from elenctic.explanation import (
    Aggregate,
    Blocked,
    Chosen,
    Counterexample,
    Derived,
    Explanation,
    Fact,
    Handle,
    Minimality,
    Node,
    NoRule,
    NotChosen,
    Rule,
    TheoryAtom,
    Unexpanded,
    Unexplained,
    Unsupported,
)
from elenctic.holding import Holding, positive_atom
from elenctic.instances import Instances, order
from elenctic.literals import Symbol
from elenctic.search import Limit
from elenctic.written import Writer, choice_bounds, negated, values_of

_NOT: Final = "not "


@dataclass(frozen=True, slots=True)
class _Present:
    atom: Symbol


@dataclass(frozen=True, slots=True)
class _Absent:
    atom: Symbol
    depth: int


@dataclass(frozen=True, slots=True)
class _Branch:
    """One instance that could derive an absent atom, under the handle of that absence."""

    parent: Handle
    handle: Handle
    instance: Instance
    depth: int


@dataclass(frozen=True, slots=True)
class _Counted:
    """An aggregate of an instance's body, at `at`, whose absent atoms are one below `depth`."""

    instance: Instance
    at: int
    depth: int


@dataclass(frozen=True, slots=True)
class _Theory:
    instance: Instance
    at: int


type _Task = _Present | _Absent | _Branch | _Counted | _Theory


class _Explainer:
    """The explainer of atoms in one answer set, from the instances that could derive them."""

    def __init__(
        self,
        instances: Instances,
        atoms: frozenset[Symbol],
        counterexample: Counterexample,
        max_depth: int | Limit,
    ) -> None:
        self._instances = instances
        self._atoms = atoms
        self._counterexample = counterexample
        self._max_depth = max_depth
        self._index = counterexample.index
        self._at = Holding(instances, atoms)
        self._writer = Writer(instances)
        self._support = self._supported()

    # -- support ------------------------------------------------------------------------------

    def _dependencies(self, instance: Instance) -> list[Symbol] | None:
        """Name the atoms an instance's support rests on, or `None` if its body does not hold."""
        clause = instance.clause
        if not clause.readable:
            return None
        pairs = zip(clause.condition, instance.condition, strict=True)
        if not all(self._at.condition_holds(part, slot) for part, slot in pairs):
            return None
        needed = [
            slot
            for part, slot in zip(clause.condition, instance.condition, strict=True)
            if positive_atom(part)
        ]
        for at, (part, slot) in enumerate(zip(clause.body, instance.body, strict=True)):
            if not self._at.part_holds(instance, at, part, slot):
                return None
            needed.extend(self._resting(instance, at, part, slot))
        return needed

    def _resting(self, instance: Instance, at: int, part: Part, slot: Symbol) -> list[Symbol]:
        """Name the atoms a literal that holds rests on: its atom, or what its aggregate counts."""
        if part.negations:
            return []
        match part.kind:
            case Kind.ATOM:
                return [slot]
            case Kind.AGGREGATE:
                return self._at.counted_atoms(instance, at, part)
            case _:
                return []

    def _supported(self) -> Mapping[Symbol, Instance]:
        """Give each atom that holds the first instance to support it, in a well-founded order."""
        found, waiting = self._waiting()
        support: dict[Symbol, Instance] = {}
        tie = itertools.count()
        ready = [(order(instance), next(tie), instance) for instance in found]
        heapq.heapify(ready)
        while ready:
            *_, instance = heapq.heappop(ready)
            if instance.head in support:
                continue
            support[instance.head] = instance
            for waiter, pending in waiting.pop(instance.head, []):
                if _released(pending):
                    heapq.heappush(ready, (order(waiter), next(tie), waiter))
        return support

    def _waiting(self) -> tuple[list[Instance], dict[Symbol, list[tuple[Instance, list[int]]]]]:
        """Sort the instances whose bodies hold into those ready now and those waiting on atoms."""
        waiting: dict[Symbol, list[tuple[Instance, list[int]]]] = {}
        ready: list[Instance] = []
        for head, candidates in self._instances.by_head.items():
            if not self._at.holds(head):
                continue
            for instance in candidates:
                needed = self._dependencies(instance)
                if needed is None:
                    continue
                pending = [len(set(needed))]
                if not needed:
                    ready.append(instance)
                for atom in set(needed):
                    waiting.setdefault(atom, []).append((instance, pending))
        return ready, waiting

    # -- nodes --------------------------------------------------------------------------------

    def explain(self, roots: Sequence[Symbol]) -> Explanation:
        """Explain each root, sharing each node among every reason it serves."""
        nodes: dict[Handle, Node] = {}
        stack: list[_Task] = [
            _Present(atom) if self._at.holds(atom) else _Absent(atom, 0) for atom in reversed(roots)
        ]
        while stack:
            task = stack.pop()
            handle = self._handle(task)
            if handle in nodes:
                continue
            node, below = self._node(task, handle)
            nodes[handle] = node
            stack.extend(reversed(below))
        handles = tuple(
            dict.fromkeys(
                self._handle(_Present(a) if self._at.holds(a) else _Absent(a, 0)) for a in roots
            )
        )
        complete = not any(isinstance(node.reason, Unexpanded) for node in nodes.values())
        return Explanation(
            self._counterexample,
            handles,
            tuple(nodes.values()),
            Minimality.NONE,
            self._max_depth,
            complete,
        )

    def _handle(self, task: _Task) -> Handle:
        match task:
            case _Present(atom):
                return f"{self._index}/{atom}"
            case _Absent(atom, _):
                return f"{self._index}/{_NOT}{atom}"
            case _Branch(_, handle, _, _):
                return handle
            case _Counted(instance, at, _):
                part = instance.clause.body[at]
                text = ground_text(atom_of(part), values_of(instance))
                holds = self._at.value(instance, at, part).holds
                return f"{self._index}/{'' if holds else _NOT}{text}"
            case _Theory(instance, at):
                text = ground_text(atom_of(instance.clause.body[at]), values_of(instance))
                holds = self._instances.theory_holds(self._atoms, instance, at)
                return f"{self._index}/{'' if holds else _NOT}{text}"

    def _node(self, task: _Task, handle: Handle) -> tuple[Node, list[_Task]]:
        match task:
            case _Present(atom):
                return self._present(atom, handle)
            case _Absent(atom, depth):
                return self._absent(atom, depth, handle)
            case _Branch(_, _, instance, depth):
                return self._branch(instance, depth, handle)
            case _Counted(instance, at, depth):
                return self._counted(instance, at, depth, handle)
            case _Theory(instance, at):
                return self._theory(instance, at, handle)

    def _present(self, atom: Symbol, handle: Handle) -> tuple[Node, list[_Task]]:
        instance = self._support.get(atom)
        if instance is None:
            return Node(handle, str(atom), holds=True, reason=Unexplained(self._unread(atom))), []
        clause = instance.clause
        if clause.form is Form.FACT:
            return Node(handle, str(atom), holds=True, reason=Fact(clause.rule)), []
        below: list[_Task] = [
            _Present(slot)
            for part, slot in zip(clause.condition, instance.condition, strict=True)
            if positive_atom(part)
        ]
        conditions: list[str] = []
        for at, (part, slot) in enumerate(zip(clause.body, instance.body, strict=True)):
            step = self._step(instance, at, part, slot)
            if isinstance(step, str):
                conditions.append(step)
            else:
                below.append(step)
        reason = (
            self._choice(instance, chosen=True)
            if clause.form in _CHOOSING
            else Derived(
                clause.rule, instance.substitution, self._writer.text(instance), tuple(conditions)
            )
        )
        return Node(
            handle, str(atom), holds=True, reason=reason, children=self._handles(below)
        ), below

    def _step(self, instance: Instance, at: int, part: Part, slot: Symbol) -> _Task | str:
        """Give the task that supports a body literal that holds, or its text if none is needed."""
        match part.kind:
            case Kind.ATOM if part.negations == 0:
                return _Present(slot)
            case Kind.ATOM:
                return negated(part.negations, str(slot))
            case Kind.AGGREGATE:
                return _Counted(instance, at, 0)
            case Kind.THEORY:
                return _Theory(instance, at)
            case _:
                return ground_text(part.node, values_of(instance))

    def _unread(self, atom: Symbol) -> Rule | None:
        unread = [i for i in self._instances.candidates(atom) if not i.clause.readable]
        return unread[0].clause.rule if unread else None

    def _choice(self, instance: Instance, *, chosen: bool) -> Chosen | NotChosen:
        clause = instance.clause
        group = {i.head for i in self._instances.group(instance) if self._at.holds(i.head)}
        lower, upper = choice_bounds(instance)
        kind = Chosen if chosen else NotChosen
        return kind(
            clause.rule,
            instance.substitution,
            self._writer.text(instance),
            lower,
            upper,
            len(group),
        )

    def _absent(self, atom: Symbol, depth: int, handle: Handle) -> tuple[Node, list[_Task]]:
        if not isinstance(self._max_depth, Limit) and depth >= self._max_depth:
            return Node(handle, str(atom), holds=False, reason=Unexpanded(depth)), []
        candidates = self._instances.candidates(atom)
        if not candidates:
            return Node(handle, str(atom), holds=False, reason=NoRule()), []
        keys: dict[str, int] = {}
        below: list[_Task] = []
        for instance in candidates:
            key = instance.key
            seen = keys.get(key, 0)
            keys[key] = seen + 1
            name = f"{handle}#{key}" + (f".{seen}" if seen else "")
            below.append(_Branch(handle, name, instance, depth))
        return (
            Node(
                handle,
                str(atom),
                holds=False,
                reason=Unsupported(len(candidates)),
                children=self._handles(below),
            ),
            below,
        )

    def _branch(self, instance: Instance, depth: int, handle: Handle) -> tuple[Node, list[_Task]]:
        clause = instance.clause
        atom = str(instance.head)
        if not clause.readable:
            return Node(handle, atom, holds=False, reason=Unexplained(clause.rule)), []
        blocked = self._blocking(instance, depth)
        if blocked is None:
            if clause.form in _CHOOSING:
                return Node(
                    handle, atom, holds=False, reason=self._choice(instance, chosen=False)
                ), []
            return Node(handle, atom, holds=False, reason=Unexplained(clause.rule)), []
        literal, task = blocked
        reason = Blocked(clause.rule, instance.substitution, self._writer.text(instance), literal)
        return Node(handle, atom, holds=False, reason=reason, children=self._handles([task])), [
            task
        ]

    def _blocking(self, instance: Instance, depth: int) -> tuple[str, _Task] | None:
        """Find the first literal, in the order written, that keeps an instance from holding."""
        clause = instance.clause
        for part, slot in zip(clause.condition, instance.condition, strict=True):
            if not self._at.condition_holds(part, slot):
                return negated(part.negations, str(slot)), self._why_not(slot, depth)
        for at, (part, slot) in enumerate(zip(clause.body, instance.body, strict=True)):
            if self._at.part_holds(instance, at, part, slot):
                continue
            match part.kind:
                case Kind.ATOM:
                    return negated(part.negations, str(slot)), self._why_not(slot, depth)
                case Kind.AGGREGATE:
                    return ground_text(part.node, values_of(instance)), _Counted(
                        instance, at, depth
                    )
                case _:
                    return ground_text(part.node, values_of(instance)), _Theory(instance, at)
        return None

    def _why_not(self, slot: Symbol, depth: int) -> _Task:
        """Say why an atom literal does not hold: its atom is absent, or (under `not`) present."""
        return _Present(slot) if self._at.holds(slot) else _Absent(slot, depth + 1)

    def _counted(
        self, instance: Instance, at: int, depth: int, handle: Handle
    ) -> tuple[Node, list[_Task]]:
        part = instance.clause.body[at]
        found = self._at.value(instance, at, part)
        below: list[_Task] = [
            _Present(slot)
            for element in found.counted
            for condition, slot in zip(part.elements[element.index], element.condition, strict=True)
            if positive_atom(condition)
        ]
        if not found.holds:
            for element in found.missing:
                for condition, slot in zip(
                    part.elements[element.index], element.condition, strict=True
                ):
                    if not self._at.condition_holds(condition, slot):
                        below.append(self._why_not(slot, depth))
                        break
        unique = list(dict.fromkeys(below))
        text = ground_text(atom_of(part), values_of(instance))
        reason = Aggregate(
            instance.clause.rule,
            instance.substitution,
            self._writer.text(instance),
            text,
            found.value,
            found.guard,
        )
        return Node(
            handle, text, holds=found.holds, reason=reason, children=self._handles(unique)
        ), unique

    def _theory(self, instance: Instance, at: int, handle: Handle) -> tuple[Node, list[_Task]]:
        part = instance.clause.body[at]
        text = ground_text(atom_of(part), values_of(instance))
        holds = self._instances.theory_holds(self._atoms, instance, at)
        named = self._counterexample.answer_set.assignment
        assignment = frozenset(v for v in named if _mentions(text, v))
        return Node(handle, text, holds=holds, reason=TheoryAtom(text, assignment)), []

    def _handles(self, tasks: Iterable[_Task]) -> tuple[Handle, ...]:
        return tuple(dict.fromkeys(self._handle(task) for task in tasks))


_CHOOSING: Final = frozenset({Form.CHOICE, Form.DISJUNCTION})


def _released(pending: list[int]) -> bool:
    pending[0] -= 1
    return pending[0] == 0


def _mentions(text: str, valuation: Valuation) -> bool:
    name = re.escape(str(valuation.variable))
    return re.search(rf"(?<![\w']){name}(?![\w'(])", text) is not None


def explain(
    instances: Instances,
    atoms: frozenset[Symbol],
    counterexample: Counterexample,
    roots: Sequence[Symbol],
    max_depth: int | Limit,
) -> Explanation:
    """Explain each root atom in the answer set whose atoms (and recorded atoms) are `atoms`."""
    return _Explainer(instances, atoms, counterexample, max_depth).explain(roots)
