"""The ``@query`` machinery (spec §2.1, §2.4, §3): a query-formula parser (a
conjunction of literals, or the variable-binding ``q(X̄)`` form), a most-general-
unification literal-unifier, and a three-valued evaluator reading yes/no/unknown
and the binding partition off the consequence sets ⋂/⋃. It interprets no rules
(no SLDNF); it evaluates against the entailed atoms the modes compute.
"""

import re
from dataclasses import dataclass
from enum import Enum

from clingo import Symbol

from elenctic.terms import parse_litset, parse_tupleset

# The ASP lexical form of a variable: an upper-case or underscore initial.
_VARIABLE = re.compile(r"[A-Z_][A-Za-z0-9_']*")


class Answer(Enum):
    """The three-valued query answer (Def 2.2.2, spec §2.1)."""

    yes = "yes"
    no = "no"
    unknown = "unknown"


@dataclass(frozen=True, slots=True)
class Var:
    """A query variable (an upper-case / underscore identifier in ``q(X̄)``)."""

    name: str


@dataclass(frozen=True, slots=True)
class QueryLiteral:
    """A (possibly non-ground) query literal: functor, strong-negation sign, and a
    per-position list of either a :class:`Var` or a ground ``Symbol`` (spec §2.1)."""

    name: str
    positive: bool
    args: tuple[Var | Symbol, ...]

    @property
    def arity(self) -> int:
        return len(self.args)


@dataclass(frozen=True, slots=True)
class GroundQuery:
    """A ground conjunctive query ``A { l1, …, ln }`` (v1 is conjunctive-only, §2.1)."""

    answer: Answer
    conjuncts: tuple[Symbol, ...]


@dataclass(frozen=True, slots=True)
class BindingQuery:
    """A variable-binding query ``A { q(X̄) } = { B }`` (spec §2.1)."""

    answer: Answer
    goal: QueryLiteral
    bindings: frozenset[tuple[Symbol, ...]]


type Query = GroundQuery | BindingQuery


def parse_query(answer: str, payload: str) -> Query:
    """Parse a ``@query`` payload into a :class:`GroundQuery` or :class:`BindingQuery` (§2.1)."""
    ans = _parse_answer(answer)
    if "=" in payload:  # the binding form: { q(X̄) } = { B }
        goal_text, _, tuples_text = payload.partition("=")
        goal = _parse_goal(_unbrace(goal_text))
        bindings = parse_tupleset(_unbrace(tuples_text), goal.arity)
        return BindingQuery(ans, goal, frozenset(bindings))
    return GroundQuery(ans, parse_litset(_unbrace(payload)))


def _parse_answer(answer: str) -> Answer:
    try:
        return Answer(answer.strip())
    except ValueError as exc:
        raise ValueError(f"query answer must be yes|no|unknown, got {answer!r}") from exc


def _unbrace(text: str) -> str:
    stripped = text.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        raise ValueError(f"expected a brace set, got {text!r}")
    return stripped[1:-1].strip()


def _parse_goal(text: str) -> QueryLiteral:
    """Parse a v1 binding-query goal: one literal ``q(X̄)`` / ``-q(X̄)`` whose arguments are
    variables or ground terms. Ground arguments go through clingo's term parser; variables
    are the ASP lexical form. Richer non-ground goals (joins) are reserved for §11 (spec §2.1)."""
    positive = not text.startswith("-")
    body = text if positive else text[1:].strip()
    name: str
    args: tuple[Var, ...]
    if "(" not in body:
        name, args = body, ()
    elif not body.endswith(")"):
        raise ValueError(f"malformed query goal: {text!r}")
    else:
        name = body[: body.index("(")].strip()
        inside = body[body.index("(") + 1 : -1]
        args = tuple(_parse_goal_arg(token.strip()) for token in inside.split(",") if token.strip())
    if not (name and name[0].islower() and name.isidentifier()):
        raise ValueError(f"query goal predicate must be a constant, got {name!r}")
    return QueryLiteral(name, positive, args)


def _parse_goal_arg(token: str) -> Var:
    """A v1 binding-goal argument must be a variable (spec §2.1; ground/compound → §11)."""
    if not _VARIABLE.fullmatch(token):
        raise ValueError(
            f"v1 binding-query goal arguments must be variables; {token!r} is not "
            "(ground-argument and compound goals are reserved, §11)"
        )
    return Var(token)
