"""The ``@query`` machinery: a query-formula parser (a
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
the conjunctive non-ground join are reserved.
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
    """The three-valued query answer (Def 2.2.2)."""

    yes = "yes"
    no = "no"
    unknown = "unknown"


class QueryForm(Enum):
    """The four query forms that route and read differently. See :func:`classify` — the
    single classifier ``run._query_mode`` and ``checks.query_matches`` share."""

    SINGLETON_GROUND = "singleton-ground"
    CONJUNCTIVE_GROUND = "conjunctive-ground"
    BINDING_SETTLED = "binding-settled"
    BINDING_UNKNOWN = "binding-unknown"


@dataclass(frozen=True, slots=True)
class Var:
    """A query variable (an upper-case / underscore identifier in ``q(X̄)``)."""

    name: str


@dataclass(frozen=True, slots=True)
class QueryLiteral:
    """A query literal: functor, strong-negation sign, and per-position arguments. The type
    admits ground arguments (the unifier is general), but the v1 parser produces all-variable
    goals (Def 2.2.2); partially-ground goals are reserved."""

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
    """A ground conjunctive query ``A { l1, …, ln }`` (v1 is conjunctive-only). The conjuncts
    are literals (atoms or strong-negation ``-atoms``), enforced at construction so the evaluators
    and ``contrary`` never face a non-literal term, and so an empty (vacuously-true) conjunction is
    unrepresentable — mirroring ``terms.parse_litset`` at the type boundary."""

    answer: Answer
    conjuncts: tuple[Symbol, ...]

    def __post_init__(self) -> None:
        if not self.conjuncts:
            raise ValueError("a ground query needs at least one conjunct")
        if any(conjunct.type is not SymbolType.Function for conjunct in self.conjuncts):
            raise ValueError(
                f"@query conjuncts must be literals (atoms or -atoms); got {self.conjuncts}"
            )


@dataclass(frozen=True, slots=True)
class BindingQuery:
    """A variable-binding query ``A { q(X̄) } = { B }``. ``bindings`` are
    variable-binding tuples (arity = number of distinct variables, Def 2.2.2)."""

    answer: Answer
    goal: QueryLiteral
    bindings: frozenset[tuple[Symbol, ...]]


type Query = GroundQuery | BindingQuery


def parse_query(answer: str, payload: str) -> Query:
    """Parse a ``@query`` payload into a :class:`GroundQuery` or :class:`BindingQuery`.

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
    argument must be a variable; partially-ground goals are reserved."""
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
    ground argument (a partially-ground goal) is reserved."""
    if not _VARIABLE.fullmatch(token):
        raise ValueError(
            f"v1 binding-query goals are all-variable (Def 2.2.2); {token!r} is not a variable "
            "(partially-ground goals are reserved)"
        )
    return Var(token)


# --- evaluation (against the entailed atoms the modes compute; no SLDNF) ---


def contrary_literal(goal: QueryLiteral) -> QueryLiteral:
    """The contrary of a query literal: flip its strong-negation sign."""
    return QueryLiteral(goal.name, not goal.positive, goal.args)


def unify(goal: QueryLiteral, atom: Symbol) -> dict[str, Symbol] | None:
    """Most-general unification of a (possibly non-ground) query literal against one ground atom.

    Returns the variable substitution if the atom matches functor, sign, arity, every ground
    position, and repeated-variable consistency; otherwise ``None``. The unifier is general (it
    handles ground argument positions for a future power-up); the v1 parser only feeds it
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
    conjuncts: tuple[Symbol, ...], census: frozenset[frozenset[Symbol]]
) -> Answer:
    """The three-valued answer to a ground *conjunctive* query (Gelfond–Kahl Def 2.2.2, corrected
    per the published errata to the 2014 textbook — ``krr_book.html#errata``). Strong-Kleene
    evaluation over the answer-set census: in a model M the conjunction is true iff every conjunct
    is in M, false iff some conjunct's *contrary* is in M (else unknown-in-M); the answer is **yes**
    iff true in all answer sets, **no** iff false in all, else **unknown**.

    ``census`` is the *set* of shown projections ``{shown(M)}`` (what ``Observable.shown`` carries),
    so a ``@query`` conjunct must be ``#show``-visible (a discovery precondition). A conjunct is
    shown, so false-in-M depends only on ``shown(M)``: evaluating over the set of distinct shown
    projections is exact, and projection (which preserves that set) does not change the answer. The
    census is needed, not ⋂ — "false in all" is ``∀M ∃i: l̄i∈M``, where each model may falsify a
    *different* conjunct, which ⋂/⋃ cannot express (the old ``∃i: l̄i∈⋂`` was the wrong, stronger ∃∀
    reading).

    Precondition: ``census`` is non-empty (AS(P)=∅ is the ``Inconsistent`` arm upstream, and a
    ``ConsistentEnumeration`` carries ≥1 observable by construction). An empty census is a caller
    bug, raised rather than answered with a vacuous ``yes`` — a correctness oracle fails loud.
    """
    if not census:
        raise ValueError("conjunctive_answer needs a non-empty census (AS(P)=∅ is upstream)")
    contraries = tuple(contrary(conjunct) for conjunct in conjuncts)
    # Answer sets are consistent, so false-in-M (∃i l̄i∈M) ⇒ not-true-in-M; the yes-branch above
    # has excluded all-true, so this elif is sound (no model is both all-true and falsified).
    if all(all(conjunct in model for conjunct in conjuncts) for model in census):
        return Answer.yes
    if all(any(neg in model for neg in contraries) for model in census):
        return Answer.no
    return Answer.unknown


def binding_set(
    goal: QueryLiteral,
    answer: Answer,
    cautious: frozenset[Symbol],
    brave: frozenset[Symbol] | None,
) -> set[tuple[Symbol, ...]]:
    """The binding tuples yielding ``answer`` for ``goal``. yes/no read the cautious
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


def classify(query: Query) -> QueryForm:
    """The query's form — the single classifier that ``run._query_mode`` (which run it
    rides) and ``checks.query_matches`` (which fields it reads, and how it decides) both consume, so
    route and read can never disagree on what a query is. The ``n == 1`` singleton boundary and the
    ``unknown``-binding split live here, once."""
    match query:
        case GroundQuery(_, conjuncts) if len(conjuncts) == 1:
            return QueryForm.SINGLETON_GROUND
        case GroundQuery():
            return QueryForm.CONJUNCTIVE_GROUND
        case BindingQuery(answer=Answer.unknown):
            return QueryForm.BINDING_UNKNOWN
        case BindingQuery():
            return QueryForm.BINDING_SETTLED
        case _:
            assert_never(query)
