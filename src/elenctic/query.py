"""The ``@query`` machinery (spec §2.1, §2.4, §3): a query-formula parser (a
conjunction of literals, or the variable-binding ``q(X̄)`` form), a most-general-
unification literal-unifier, and a three-valued evaluator reading yes/no/unknown
and the binding partition off the consequence sets ⋂/⋃. It interprets no rules
(no SLDNF); it evaluates against the entailed atoms the modes compute.

The binding form adheres to Gelfond–Kahl Def 2.2.2: for a query ``q(X1, …, Xn)``,
where ``X1, …, Xn`` is the list of (distinct) variables occurring in ``q``, an answer
is a sequence of ground terms ``t1, …, tn`` such that ``Π |= q(t1, …, tn)``. v1 holds
to the definition strictly: binding goals are **all-variable** (every argument is a
variable). The binding-tuple arity is the number of **distinct** variables, so a
repeated-variable goal ``q(X, X)`` has one binding column. Partially-ground goals and
the conjunctive non-ground join are reserved (§11).
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import assert_never

from clingo import Symbol, SymbolType

from elenctic.terms import contrary, parse_litset, parse_tupleset

# The ASP lexical forms: a variable (upper-case / underscore initial), a constant (lower-case).
_VARIABLE = re.compile(r"[A-Z_][A-Za-z0-9_']*")
_CONSTANT = re.compile(r"[a-z][A-Za-z0-9_']*")


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
    """A query literal: functor, strong-negation sign, and per-position arguments. The type
    admits ground arguments (the unifier is general), but the v1 parser produces all-variable
    goals (Def 2.2.2); partially-ground goals are reserved (§11)."""

    name: str
    positive: bool
    args: tuple[Var | Symbol, ...]

    @property
    def arity(self) -> int:
        """The predicate arity (number of argument positions); used for unification."""
        return len(self.args)

    @property
    def variables(self) -> tuple[str, ...]:
        """Distinct variable names occurring in the goal, in order of first occurrence —
        the ``X1, …, Xn`` of Def 2.2.2, and the arity of the binding tuples."""
        ordered: dict[str, None] = {}
        for arg in self.args:
            if isinstance(arg, Var):
                ordered.setdefault(arg.name, None)
        return tuple(ordered)


@dataclass(frozen=True, slots=True)
class GroundQuery:
    """A ground conjunctive query ``A { l1, …, ln }`` (v1 is conjunctive-only, §2.1)."""

    answer: Answer
    conjuncts: tuple[Symbol, ...]


@dataclass(frozen=True, slots=True)
class BindingQuery:
    """A variable-binding query ``A { q(X̄) } = { B }`` (spec §2.1). ``bindings`` are
    variable-binding tuples (arity = number of distinct variables, Def 2.2.2)."""

    answer: Answer
    goal: QueryLiteral
    bindings: frozenset[tuple[Symbol, ...]]


type Query = GroundQuery | BindingQuery


def parse_query(answer: str, payload: str) -> Query:
    """Parse a ``@query`` payload into a :class:`GroundQuery` or :class:`BindingQuery` (§2.1).

    Routes on the first ``=`` (the binding separator); a v1 all-variable goal and its
    binding tuples contain no ``=``, so the partition is unambiguous.
    """
    ans = _parse_answer(answer)
    if "=" in payload:  # the binding form: { q(X̄) } = { B }
        goal_text, _, tuples_text = payload.partition("=")
        goal = _parse_goal(_unbrace(goal_text))
        if not goal.variables:
            raise ValueError(
                "a binding query goal must contain at least one variable; "
                "use the ground form '@query A { … }' for a ground goal"
            )
        bindings = parse_tupleset(_unbrace(tuples_text), len(goal.variables))
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
    """Parse an all-variable binding-query goal ``q(X̄)`` / ``-q(X̄)`` (Def 2.2.2). Every
    argument must be a variable; partially-ground goals are reserved (§11)."""
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
    if not _CONSTANT.fullmatch(name):
        raise ValueError(f"query goal predicate must be an ASP constant, got {name!r}")
    return QueryLiteral(name, positive, args)


def _parse_goal_arg(token: str) -> Var:
    """A v1 binding-goal argument must be a variable (Def 2.2.2 all-variable query); a
    ground argument (a partially-ground goal) is reserved (§11)."""
    if not _VARIABLE.fullmatch(token):
        raise ValueError(
            f"v1 binding-query goals are all-variable (Def 2.2.2); {token!r} is not a variable "
            "(partially-ground goals are reserved, §11)"
        )
    return Var(token)


# --- evaluation (against the entailed atoms the modes compute; no SLDNF, spec §3) ---


def contrary_literal(goal: QueryLiteral) -> QueryLiteral:
    """The contrary of a query literal: flip its strong-negation sign (spec §2.1)."""
    return QueryLiteral(goal.name, not goal.positive, goal.args)


def unify(goal: QueryLiteral, atom: Symbol) -> dict[str, Symbol] | None:
    """Most-general unification of a (possibly non-ground) query literal against one ground atom.

    Returns the variable substitution if the atom matches functor, sign, arity, every ground
    position, and repeated-variable consistency; otherwise ``None``. The unifier is general (it
    handles ground argument positions for the §11 power-up); the v1 parser only feeds it
    all-variable goals (Def 2.2.2).
    """
    if (
        atom.type is not SymbolType.Function
        or atom.name != goal.name
        or atom.positive != goal.positive
        or len(atom.arguments) != goal.arity
    ):
        return None
    subst: dict[str, Symbol] = {}
    for slot, arg in zip(goal.args, atom.arguments, strict=True):
        if isinstance(slot, Var):
            if subst.setdefault(slot.name, arg) != arg:
                return None  # a repeated variable must bind consistently
        elif slot != arg:
            return None  # a ground position must match exactly
    return subst


def _bindings_over(goal: QueryLiteral, atoms: frozenset[Symbol]) -> set[tuple[Symbol, ...]]:
    """The distinct-variable binding tuples of the atoms that unify with ``goal`` (Def 2.2.2)."""
    bindings: set[tuple[Symbol, ...]] = set()
    for atom in atoms:
        subst = unify(goal, atom)
        if subst is not None:
            bindings.add(tuple(subst[name] for name in goal.variables))
    return bindings


def ground_answer(conjuncts: tuple[Symbol, ...], intersection: frozenset[Symbol]) -> Answer:
    """DEPRECATED — superseded by ``singleton_answer`` (⋂) and ``conjunctive_answer`` (census).

    Its conjunctive "no" (``∃i: l̄i ∈ ⋂``) is the wrong ∃∀ reading corrected by the errata
    (see ``conjunctive_answer``). Kept only until ``checks.py`` adopts the new evaluators, then
    removed (field-compatibility keystone, Task 3).
    """
    if all(conjunct in intersection for conjunct in conjuncts):
        return Answer.yes
    if any(contrary(conjunct) in intersection for conjunct in conjuncts):
        return Answer.no
    return Answer.unknown


def singleton_answer(literal: Symbol, cautious: frozenset[Symbol]) -> Answer:
    """The three-valued answer to a ground *singleton* query off ⋂ (Gelfond–Kahl Def 2.2.2):
    yes iff the literal is entailed, no iff its contrary is entailed, else unknown. ⋂ suffices —
    for one literal the corrected "false in all answer sets" rule ``∀M: l̄∈M`` is exactly ``l̄∈⋂``.
    """
    if literal in cautious:
        return Answer.yes
    if contrary(literal) in cautious:
        return Answer.no
    return Answer.unknown


def conjunctive_answer(
    conjuncts: tuple[Symbol, ...], models: tuple[frozenset[Symbol], ...]
) -> Answer:
    """The three-valued answer to a ground *conjunctive* query (Gelfond–Kahl Def 2.2.2, corrected
    per the published errata to the 2014 textbook — ``krr_book.html#errata``; confirmed 2026-06-19).
    Strong-Kleene evaluation over the answer-set census: in a model M the conjunction is true iff
    every conjunct is in M, false iff some conjunct's *contrary* is in M (else unknown-in-M); the
    answer is **yes** iff true in all answer sets, **no** iff false in all, else **unknown**.

    ``models`` is each answer set as the program makes it observable — its ``shown(M)`` projection
    (spec §2.0; the object ``Observable.shown`` carries), so a ``@query`` conjunct must be
    ``#show``-visible (a discovery precondition, spec §5). The census is required, not ⋂: "false in
    all" is ``∀M ∃i: l̄i∈M`` — each model may falsify a *different* conjunct, which ⋂/⋃ cannot
    express (the old ``∃i: l̄i∈⋂`` was the wrong, strictly stronger ∃∀ reading).

    Precondition: ``models`` is non-empty (AS(P)=∅ is the ``Inconsistent`` arm upstream, and a
    ``ConsistentEnumeration`` carries ≥1 observable by construction). An empty census is a caller
    bug, raised rather than answered with a vacuous ``yes`` — a correctness oracle fails loud.
    """
    if not models:
        raise ValueError("conjunctive_answer needs a non-empty census (AS(P)=∅ is upstream)")
    contraries = tuple(contrary(conjunct) for conjunct in conjuncts)
    # Answer sets are consistent, so false-in-M (∃i l̄i∈M) ⇒ not-true-in-M; the yes-branch above
    # has excluded all-true, so this elif is sound (no model is both all-true and falsified).
    if all(all(conjunct in model for conjunct in conjuncts) for model in models):
        return Answer.yes
    if all(any(neg in model for neg in contraries) for model in models):
        return Answer.no
    return Answer.unknown


def binding_set(
    goal: QueryLiteral,
    answer: Answer,
    cautious: frozenset[Symbol],
    brave: frozenset[Symbol] | None,
) -> set[tuple[Symbol, ...]]:
    """The binding tuples yielding ``answer`` for ``goal`` (spec §2.1). yes/no read the cautious
    consequences ⋂; unknown additionally needs the brave consequences ⋃ (the entertained-but-
    unsettled middle)."""
    match answer:
        case Answer.yes:
            return _bindings_over(goal, cautious)
        case Answer.no:
            return _bindings_over(contrary_literal(goal), cautious)
        case Answer.unknown:
            if brave is None:
                raise ValueError(
                    "an unknown-binding query needs the brave consequences ⋃ "
                    "(route it to a full enumeration)"
                )
            entailed_yes = _bindings_over(goal, cautious)
            entailed_no = _bindings_over(contrary_literal(goal), cautious)
            brave_domain = _bindings_over(goal, brave) | _bindings_over(
                contrary_literal(goal), brave
            )
            return brave_domain - entailed_yes - entailed_no
        case _:
            assert_never(answer)


def satisfied(
    query: Query,
    cautious: frozenset[Symbol],
    brave: frozenset[Symbol] | None,
    models: tuple[frozenset[Symbol], ...] | None,
) -> bool:
    """The boolean convenience for *embedders*: whether the program's computed answer matches the
    contract's (spec §3). The check layer (``checks.py``) calls ``singleton_answer`` /
    ``conjunctive_answer`` / ``binding_set`` directly to build a diagnostic. ``models`` (the
    answer-set census) is required for a conjunctive ground query, ``brave`` for an unknown binding.
    """
    match query:
        case GroundQuery(answer, conjuncts) if len(conjuncts) == 1:
            return singleton_answer(conjuncts[0], cautious) is answer
        case GroundQuery(answer, conjuncts):
            if not models:
                raise ValueError("a conjunctive ground query needs a non-empty model census")
            return conjunctive_answer(conjuncts, models) is answer
        case BindingQuery(answer, goal, bindings):
            return binding_set(goal, answer, cautious, brave) == set(bindings)
        case _:
            assert_never(query)
