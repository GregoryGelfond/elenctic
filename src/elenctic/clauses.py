"""A program's rules as the explanation reads them: clauses, the parts of their bodies, instances.

A rule is read into clauses, one for each atom its head can derive. An instance is a clause with
values for its variables, recorded with what its body literals and guards ground to.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum, auto
from typing import Final

from clingo import Symbol
from clingo.ast import (
    AST,
    AggregateFunction,
    ASTType,
    ComparisonOperator,
    Sign,
    Transformer,
)

from elenctic import tree
from elenctic.explanation import Rule
from elenctic.substitution import Substitution
from elenctic.terms import Variable

_ANONYMOUS: Final = "_"

_OPERATORS: Final[Mapping[ComparisonOperator, str]] = {
    ComparisonOperator.Equal: "=",
    ComparisonOperator.NotEqual: "!=",
    ComparisonOperator.LessThan: "<",
    ComparisonOperator.LessEqual: "<=",
    ComparisonOperator.GreaterThan: ">",
    ComparisonOperator.GreaterEqual: ">=",
}
"""How clingo writes each comparison."""

_MIRRORED: Final[Mapping[str, str]] = {
    "=": "=",
    "!=": "!=",
    "<": ">",
    "<=": ">=",
    ">": "<",
    ">=": "<=",
}

_FUNCTIONS: Final[Mapping[AggregateFunction, str]] = {
    AggregateFunction.Count: "count",
    AggregateFunction.Sum: "sum",
    AggregateFunction.SumPlus: "sum+",
}
"""The aggregate functions whose value is read here; `#min` and `#max` are not yet."""


class Form(Enum):
    """How a clause derives its atom."""

    FACT = auto()
    RULE = auto()
    CHOICE = auto()
    DISJUNCTION = auto()


class Kind(Enum):
    """What a literal of a body or condition is."""

    ATOM = auto()
    CONDITION = auto()
    """A comparison or a Boolean constant, which grounding decides."""
    AGGREGATE = auto()
    THEORY = auto()


@dataclass(frozen=True, slots=True)
class Guard:
    """A bound on an aggregate or a choice: `written` as in the source, `operator` from its value.

    `2 <= #count { … }` is written `<=` on the left, and its value must be `>=` 2.
    """

    written: str
    left: bool

    @property
    def operator(self) -> str:
        """How the value compares with the bound, as if the bound were written on the right."""
        return _MIRRORED[self.written] if self.left else self.written


@dataclass(frozen=True, slots=True)
class Part:
    """A literal of a body or a condition: its kind, its `not`s, and the literal itself."""

    kind: Kind
    negations: int
    node: AST
    function: str = ""
    guards: tuple[Guard, ...] = ()
    elements: tuple[tuple[Part, ...], ...] = ()
    """The condition of each element of an aggregate."""


@dataclass(frozen=True, slots=True)
class Clause:
    """One atom-deriving head of one rule, with the body it shares with the rule's other heads.

    `variables` are the rule's own, then those local to the clause's element; `shared` counts the
    former.
    A clause that is not `readable` holds a construct no reason covers yet.
    """

    number: int
    piece: int
    rule: Rule
    form: Form
    variables: tuple[str, ...]
    shared: int
    head: AST
    condition: tuple[Part, ...]
    body: tuple[Part, ...]
    readable: bool
    statement: AST
    bounds: tuple[Guard, ...] = ()


@dataclass(frozen=True, slots=True)
class Instance:
    """A ground instance of a clause: its values and what its parts ground to."""

    clause: Clause
    values: tuple[Symbol, ...]
    head: Symbol
    body: tuple[Symbol, ...]
    condition: tuple[Symbol, ...]
    bounds: tuple[Symbol, ...]

    @property
    def shared(self) -> tuple[Symbol, ...]:
        """The values of the rule's own variables, which its body aggregates are keyed by."""
        return self.values[: self.clause.shared]

    @property
    def substitution(self) -> Substitution:
        """Each variable of the clause, bound to its value in this instance."""
        return Substitution(
            {
                Variable(name): value
                for name, value in zip(self.clause.variables, self.values, strict=True)
            }
        )

    @property
    def key(self) -> str:
        """The rule instance in a handle: `r8(ann,db,admin)`, or `r3` with no variables."""
        values = f"({','.join(map(str, self.values))})" if self.values else ""
        return f"r{self.clause.rule.statement}{values}"


@dataclass(frozen=True, slots=True)
class Weak:
    """A weak constraint, or one element of a `#minimize`: where it is and its variables."""

    rule: Rule
    variables: tuple[str, ...]


class _Names(Transformer):
    """A collector of the named variables of a statement, in the order they are first written.

    Variables whose names begin with `fresh` were named by the relaxation, and are left out.
    """

    def __init__(self, fresh: str) -> None:
        self._fresh = fresh
        self.found: list[str] = []

    def visit_Variable(self, variable: AST) -> AST:  # noqa: N802
        name = tree.name(variable)
        if name != _ANONYMOUS and name not in self.found and not name.startswith(self._fresh):
            self.found.append(name)
        return variable


class _GlobalNames(_Names):
    """A collector of a rule's variables outside its elements, whose variables are their own."""

    def visit_BodyAggregateElement(self, element: AST) -> AST:  # noqa: N802
        return element

    def visit_ConditionalLiteral(self, element: AST) -> AST:  # noqa: N802
        return element

    def visit_TheoryAtomElement(self, element: AST) -> AST:  # noqa: N802
        return element

    def visit_HeadAggregateElement(self, element: AST) -> AST:  # noqa: N802
        return element


def names_in(node: AST, fresh: str) -> list[str]:
    """Name the variables of `node`, in the order they are first written, without `_`."""
    names = _Names(fresh)
    names.visit(node)
    return names.found


def global_names_in(node: AST, fresh: str) -> list[str]:
    """Name the variables of a rule that stand outside its elements, in the order written."""
    names = _GlobalNames(fresh)
    names.visit(node)
    return names.found


def ground_text(node: AST, values: Mapping[str, Symbol]) -> str:
    """Write `node` with each variable that has a value replaced by it."""
    return str(tree.renamed(node, lambda name: str(values[name]) if name in values else name))


def anonymous_named(node: AST, fresh: str) -> AST:
    """Name each anonymous variable of `node` apart, so a relaxed rule can carry its term.

    The names begin with `fresh`, which no variable of the program begins with.
    """
    count = 0

    def rename(name: str) -> str:
        nonlocal count
        if name != _ANONYMOUS:
            return name
        count += 1
        return f"{fresh}A{count}"

    return tree.renamed(node, rename)


def _guards(node: AST) -> tuple[Guard, ...]:
    """Read the guards of an aggregate or a choice, left first."""
    found: list[Guard] = []
    for key, left in (("left_guard", True), ("right_guard", False)):
        guard: object = getattr(node, key)
        if isinstance(guard, AST):
            found.append(
                Guard(_OPERATORS[ComparisonOperator(tree.number(guard, "comparison"))], left)
            )
    return tuple(found)


def guard_terms(node: AST) -> str:
    """Write an aggregate's guard terms as one term: `((2,),())`, empty where there is none."""
    terms: list[str] = []
    for key in ("left_guard", "right_guard"):
        guard: object = getattr(node, key)
        terms.append(f"({tree.child(guard, 'term')},)" if isinstance(guard, AST) else "()")
    return f"({','.join(terms)})"


def read_condition(literal: AST) -> Part | None:
    """Read a literal of a condition: an atom or a comparison; `None` for anything else."""
    if tree.kind(literal) is not ASTType.Literal:
        return None
    atom = tree.child(literal, "atom")
    negations = tree.number(literal, "sign")
    match tree.kind(atom):
        case ASTType.SymbolicAtom:
            return Part(Kind.ATOM, negations, literal)
        case ASTType.Comparison | ASTType.BooleanConstant:
            return Part(Kind.CONDITION, negations, literal)
        case _:
            return None


def _aggregate(literal: AST, atom: AST, negations: int) -> Part | None:
    function = _FUNCTIONS.get(AggregateFunction(tree.number(atom, "function")))
    elements: list[tuple[Part, ...]] = []
    for element in tree.children(atom, "elements"):
        parts = [read_condition(c) for c in tree.children(element, "condition")]
        if function is None or any(part is None for part in parts):
            return None
        elements.append(tuple(part for part in parts if part is not None))
    return Part(
        Kind.AGGREGATE,
        negations,
        literal,
        function or "",
        _guards(atom),
        tuple(elements),
    )


def read_part(literal: AST) -> Part | None:
    """Read a body literal; `None` for a construct no reason covers yet."""
    if tree.kind(literal) is not ASTType.Literal:
        return None
    atom = tree.child(literal, "atom")
    negations = tree.number(literal, "sign")
    match tree.kind(atom):
        case ASTType.BodyAggregate:
            return _aggregate(literal, atom, negations)
        case ASTType.TheoryAtom:
            return Part(Kind.THEORY, negations, literal)
        case _:
            return read_condition(literal)


def is_positive(literal: AST) -> bool:
    """Say whether a literal no reason covers can stay in the relaxation: it has no `not`."""
    return tree.kind(literal) is ASTType.Literal and tree.number(literal, "sign") == Sign.NoSign


def atom_of(part: Part) -> AST:
    """Return the atom of a literal, without its `not`s."""
    return tree.child(part.node, "atom")


def is_relaxed(part: Part) -> bool:
    """Say whether a literal stays in the relaxation: positive atoms, comparisons, aggregates."""
    return part.kind is not Kind.THEORY and (part.kind is Kind.CONDITION or part.negations == 0)


def slot_term(part: Part) -> str:
    """Write the term a literal grounds to in an instance: its atom, its guards, or nothing."""
    match part.kind:
        case Kind.ATOM:
            return str(tree.child(tree.child(part.node, "atom"), "symbol"))
        case Kind.AGGREGATE:
            return guard_terms(tree.child(part.node, "atom"))
        case _:
            return "()"


def tuple_text(items: Iterable[str]) -> str:
    """Write terms as one clingo tuple, with the comma a tuple of one needs."""
    listed = list(items)
    return f"({','.join(listed)}{',' if len(listed) == 1 else ''})"


@dataclass(frozen=True, slots=True)
class Head:
    """One atom a rule's head can derive, and the condition it is written under."""

    literal: AST
    condition: tuple[AST, ...]


def read_heads(head: AST) -> tuple[Form, tuple[Head, ...], tuple[Guard, ...], bool] | None:
    """Read what a head derives; `None` for a constraint or a head that derives no atom."""
    match tree.kind(head):
        case ASTType.Literal if tree.kind(tree.child(head, "atom")) is ASTType.SymbolicAtom:
            if tree.number(head, "sign") != Sign.NoSign:
                return None
            return Form.RULE, (Head(head, ()),), (), True
        case ASTType.Aggregate:
            elements = tree.children(head, "elements")
            heads = tuple(
                Head(tree.child(e, "literal"), tree.children(e, "condition")) for e in elements
            )
            return Form.CHOICE, heads, _guards(head), True
        case ASTType.Disjunction:
            elements = tree.children(head, "elements")
            heads = tuple(
                Head(tree.child(e, "literal"), tree.children(e, "condition")) for e in elements
            )
            return Form.DISJUNCTION, heads, (), True
        case ASTType.HeadAggregate:
            elements = tree.children(head, "elements")
            heads = tuple(
                Head(tree.child(tree.child(e, "condition"), "literal"), ()) for e in elements
            )
            return Form.CHOICE, heads, (), False
        case _:
            return None
