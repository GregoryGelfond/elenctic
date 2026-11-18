"""Why a claim fails in a counterexample: the nodes of an explanation, and the reason for each.

Plain values only: the library builds them, and the text and JSON views show them as they are.
"""

from dataclasses import dataclass
from enum import StrEnum, auto

from elenctic.determination import AnswerSet, Assignment, Cost, Refutation
from elenctic.literals import Atoms, Symbol
from elenctic.search import Limit
from elenctic.spans import Span
from elenctic.substitution import Substitution

type Handle = str
"""A node's name, built from what it says: `1/reach(c)`, `1/not access(ann,db)`, and for one rule
instance that could derive an absent atom, `1/not access(ann,db)#r8(ann,db,admin)`."""


@dataclass(frozen=True, slots=True)
class Rule:
    """A statement of the program: its index among the statements, its span and its text."""

    statement: int
    span: Span
    text: str


@dataclass(frozen=True, slots=True)
class Fact:
    """The atom is a fact of the program."""

    rule: Rule


@dataclass(frozen=True, slots=True)
class Derived:
    """An instance of `rule` derives the atom; its positive body atoms are the children.

    `conditions` are the other body literals that hold there, listed and not explained: negative
    literals and comparisons.
    """

    rule: Rule
    substitution: Substitution
    instance: str
    conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Chosen:
    """A choice allows the atom, and it is chosen: `chosen` of its elements, between the bounds."""

    rule: Rule
    substitution: Substitution
    instance: str
    lower: int | None
    upper: int | None
    chosen: int


@dataclass(frozen=True, slots=True)
class NotChosen:
    """A choice allows the atom, and it is not chosen: `chosen` of its elements are."""

    rule: Rule
    substitution: Substitution
    instance: str
    lower: int | None
    upper: int | None
    chosen: int


@dataclass(frozen=True, slots=True)
class Aggregate:
    """A body aggregate of an instance of `rule` comes to `value`, against its `guard`.

    The children are the elements it counts and, when it does not hold, those it could count.
    """

    rule: Rule
    substitution: Substitution
    instance: str
    atom: str
    value: int
    guard: str


@dataclass(frozen=True, slots=True)
class TheoryAtom:
    """A theory atom holds or not under the variables of the assignment it names."""

    atom: str
    assignment: Assignment


@dataclass(frozen=True, slots=True)
class Blocked:
    """An instance of `rule` could derive the atom, but `literal` of its body does not hold.

    The one child says why: the first literal in body order that does not hold.
    """

    rule: Rule
    substitution: Substitution
    instance: str
    literal: str


@dataclass(frozen=True, slots=True)
class Unsupported:
    """No rule instance derives the atom: one child for each of the `candidates` that could."""

    candidates: int


@dataclass(frozen=True, slots=True)
class NoRule:
    """No rule instance can derive the atom, however the program is solved."""


@dataclass(frozen=True, slots=True)
class Unexpanded:
    """The explanation stops here, `depth` absences below a root: its `max_depth`."""

    depth: int


@dataclass(frozen=True, slots=True)
class Unexplained:
    """A rule that elenctic does not yet read could derive the atom, so no reason is given.

    `rule` is that rule, or `None` when nothing read accounts for the atom.
    """

    rule: Rule | None


type Reason = (
    Fact
    | Derived
    | Chosen
    | NotChosen
    | Aggregate
    | TheoryAtom
    | Blocked
    | Unsupported
    | NoRule
    | Unexpanded
    | Unexplained
)


@dataclass(frozen=True, slots=True)
class Node:
    """An atom, whether it holds in the counterexample, and why; `children` are handles."""

    handle: Handle
    atom: str
    holds: bool
    reason: Reason
    children: tuple[Handle, ...] = ()


class Minimality(StrEnum):
    """What an explanation guarantees about its size."""

    NONE = auto()
    """A sound support: each atom has one reason, and none is shown to be the smallest."""


@dataclass(frozen=True, slots=True)
class Counterexample:
    """The answer set explained: the `index`-th the search read, of `read` in all.

    It is the one a claim fails in, or the one asked for by its index. `read` is `None` when the
    search did not read them all: it stopped at this one, or was truncated.
    """

    answer_set: AnswerSet
    index: int
    read: int | None


@dataclass(frozen=True, slots=True)
class Explanation:
    """Why the root atoms hold or not in the counterexample, as nodes in first-visit order.

    A node appears once, however many reasons it serves. Presence is well founded, so it has no
    cycle; an absence can lead back to itself, which is an unfounded loop. `complete` says no
    branch stopped at `max_depth`.
    """

    counterexample: Counterexample
    roots: tuple[Handle, ...]
    nodes: tuple[Node, ...]
    minimality: Minimality
    max_depth: int | Limit
    complete: bool

    def __post_init__(self) -> None:
        unexpanded = any(isinstance(node.reason, Unexpanded) for node in self.nodes)
        if self.complete == unexpanded:
            message = "an explanation is complete exactly when no node is unexpanded"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Paid:
    """One weak-constraint instance an answer set pays: `weight` at `priority`, from `rule`."""

    rule: Rule
    weight: int
    priority: int
    terms: tuple[Symbol, ...]
    substitution: Substitution


@dataclass(frozen=True, slots=True)
class Outranked:
    """The literals hold in some answer set, but the objective ranks each one below the optimum.

    `assuming` is the best cost with the literals, `optimum` the cost without them; `priority` is
    the first priority, of `priorities` (highest first), at which they differ. `optimum_only` and
    `assuming_only` are the weak-constraint instances each pays and the other does not, and
    `explanation` says why the literals are absent from the optimum.
    """

    literals: Atoms
    priorities: tuple[int, ...]
    optimum: Cost
    assuming: Cost
    priority: int
    optimum_only: tuple[Paid, ...]
    assuming_only: tuple[Paid, ...]
    explanation: Explanation


type Evidence = Explanation | Refutation | Outranked
"""What bears on a failed claim: why it fails in a counterexample, a clash of its assumptions, or
an objective that outranks what it expects."""
