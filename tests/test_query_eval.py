import pytest
from clingo import Symbol, parse_term

from elenctic.query import (
    Answer,
    BindingQuery,
    GroundQuery,
    QueryForm,
    QueryLiteral,
    Var,
    binding_set,
    classify,
    conjunctive_answer,
    contrary_literal,
    singleton_answer,
    unify,
)


def atoms(*names: str) -> frozenset[Symbol]:
    return frozenset(parse_term(name) for name in names)


@pytest.mark.parametrize(
    ("goal", "atom", "expected"),
    [
        pytest.param(QueryLiteral("p", True, (Var("X"),)), "p(a)", {"X": "a"}, id="single-var"),
        pytest.param(
            QueryLiteral("p", True, (Var("X"), Var("X"))),
            "p(a,a)",
            {"X": "a"},
            id="repeat-consistent",
        ),
        pytest.param(
            QueryLiteral("p", True, (Var("X"), Var("X"))), "p(a,b)", None, id="repeat-inconsistent"
        ),
        pytest.param(
            QueryLiteral("p", True, (Var("X"), parse_term("a"))),
            "p(s,a)",
            {"X": "s"},
            id="ground-match",
        ),
        pytest.param(
            QueryLiteral("p", True, (Var("X"), parse_term("a"))),
            "p(s,b)",
            None,
            id="ground-mismatch",
        ),
        pytest.param(QueryLiteral("p", True, (Var("X"),)), "q(a)", None, id="functor-mismatch"),
        pytest.param(QueryLiteral("p", False, (Var("X"),)), "p(a)", None, id="sign-mismatch"),
        pytest.param(QueryLiteral("p", True, ()), "p", {}, id="zero-arity-match"),
        pytest.param(QueryLiteral("p", True, ()), "q", None, id="zero-arity-mismatch"),
    ],
)
def test_unify(goal: QueryLiteral, atom: str, expected: dict[str, str] | None) -> None:
    want = {k: parse_term(v) for k, v in expected.items()} if expected is not None else None
    assert unify(goal, parse_term(atom)) == want


def test_contrary_literal_flips_sign() -> None:
    assert contrary_literal(QueryLiteral("p", True, (Var("X"),))) == QueryLiteral(
        "p", False, (Var("X"),)
    )


@pytest.mark.parametrize(
    ("literal", "cautious", "expected"),
    [
        pytest.param("start(s)", ("start(s)", "-reachable(x)"), Answer.yes, id="entailed"),
        pytest.param("reachable(x)", ("start(s)", "-reachable(x)"), Answer.no, id="contrary"),
        pytest.param("reachable(y)", ("start(s)", "-reachable(x)"), Answer.unknown, id="neither"),
        # the queried literal is itself strong-negative: contrary reachable(x) is entailed → no
        pytest.param("-reachable(x)", ("reachable(x)",), Answer.no, id="strong-negative-literal"),
    ],
)
def test_singleton_answer(literal: str, cautious: tuple[str, ...], expected: Answer) -> None:
    assert singleton_answer(parse_term(literal), atoms(*cautious)) is expected


def models(*sets: tuple[str, ...]) -> frozenset[frozenset[Symbol]]:
    return frozenset(atoms(*s) for s in sets)


@pytest.mark.parametrize(
    ("conjuncts", "census", "expected"),
    [
        # true in all answer sets → yes
        pytest.param(("a", "b"), (("a", "b"), ("a", "b", "c")), Answer.yes, id="true-in-all"),
        # THE BUG FIX: every model falsifies *some* conjunct (a different one each) → no.
        # Old ∃i:l̄i∈⋂ gave unknown; corrected ∀M∃i:l̄i∈M gives no.
        pytest.param(
            ("p(a)", "p(b)"),
            (("p(a)", "-p(b)"), ("-p(a)", "p(b)")),
            Answer.no,
            id="false-in-all-varying-conjunct",
        ),
        # one model leaves a conjunct merely unknown (not strongly false) → unknown (strong-Kleene)
        pytest.param(("a", "b"), (("a",), ("a", "b")), Answer.unknown, id="strong-kleene-unknown"),
        # overlap case (a conjunct's contrary in ⋂) still no — subset of ∀M∃i
        pytest.param(
            ("start(s)", "reachable(x)"),
            (("start(s)", "-reachable(x)"),),
            Answer.no,
            id="contrary-in-every-model",
        ),
        # THE DISCRIMINATOR: each model omits a *different* conjunct by ABSENCE (no contrary
        # present) → unknown, NOT no. The absence-twin of false-in-all-varying-conjunct; this pins
        # strong-Kleene "false in M" = l̄∈M (Example 2.2.8) for n≥2 — a closed-world impl gives no.
        pytest.param(
            ("a", "b"), (("a",), ("b",)), Answer.unknown, id="absent-not-contrary-each-model"
        ),
        # neither true-in-all nor false-in-all (true in one model, strongly false in another)
        pytest.param(
            ("a", "b"), (("a", "b"), ("-a", "b")), Answer.unknown, id="true-in-one-false-in-other"
        ),
        # a single-model census satisfying the conjunction → yes
        pytest.param(("a", "b"), (("a", "b"),), Answer.yes, id="single-model-yes"),
    ],
)
def test_conjunctive_answer(
    conjuncts: tuple[str, ...], census: tuple[tuple[str, ...], ...], expected: Answer
) -> None:
    actual = conjunctive_answer(tuple(parse_term(c) for c in conjuncts), models(*census))
    assert actual is expected


def test_conjunctive_answer_rejects_empty_census() -> None:
    # AS(P)=∅ is the Inconsistent arm upstream; an empty census fails loud, never a vacuous "yes".
    with pytest.raises(ValueError, match="census"):
        conjunctive_answer((parse_term("a"), parse_term("b")), frozenset())


def test_classify_assigns_each_query_its_form() -> None:
    # the one classifier run._query_mode and checks.query_matches share — they cannot disagree
    goal = QueryLiteral("p", True, (Var("X"),))
    assert classify(GroundQuery(Answer.yes, (parse_term("a"),))) is QueryForm.SINGLETON_GROUND
    assert (
        classify(GroundQuery(Answer.no, (parse_term("a"), parse_term("b"))))
        is QueryForm.CONJUNCTIVE_GROUND
    )
    assert classify(BindingQuery(Answer.yes, goal, frozenset())) is QueryForm.BINDING_SETTLED
    assert classify(BindingQuery(Answer.unknown, goal, frozenset())) is QueryForm.BINDING_UNKNOWN


def test_binding_set_yes_reads_intersection() -> None:
    goal = QueryLiteral("reachable", True, (Var("X"),))
    inter = atoms("reachable(s)", "reachable(a)", "reachable(t)")
    assert binding_set(goal, Answer.yes, inter, None) == {
        (parse_term("s"),),
        (parse_term("a"),),
        (parse_term("t"),),
    }


def test_binding_set_no_reads_contrary() -> None:
    goal = QueryLiteral("reachable", True, (Var("X"),))
    inter = atoms("reachable(s)", "-reachable(x)")
    assert binding_set(goal, Answer.no, inter, None) == {(parse_term("x"),)}


def test_binding_set_unknown_uses_brave_domain() -> None:
    goal = QueryLiteral("reachable", True, (Var("X"),))
    inter = atoms("reachable(s)")
    union = atoms("reachable(s)", "reachable(a)", "-reachable(b)")
    # brave domain {s, a, b} − yes {s} − no {} = {a, b}
    assert binding_set(goal, Answer.unknown, inter, union) == {
        (parse_term("a"),),
        (parse_term("b"),),
    }


def test_binding_set_unknown_requires_union() -> None:
    goal = QueryLiteral("reachable", True, (Var("X"),))
    with pytest.raises(ValueError, match="brave consequences"):
        binding_set(goal, Answer.unknown, atoms("reachable(s)"), None)


def test_binding_set_repeated_variable_one_column() -> None:
    goal = QueryLiteral("rel", True, (Var("X"), Var("X")))
    inter = atoms("rel(a,a)", "rel(b,c)")  # only rel(a,a) unifies under X=X
    assert binding_set(goal, Answer.yes, inter, None) == {(parse_term("a"),)}


def test_classify_singleton_boundary_is_arity_one() -> None:
    # the n==1 boundary lives once, in classify; both consumers inherit it
    assert classify(GroundQuery(Answer.yes, (parse_term("a"),))) is QueryForm.SINGLETON_GROUND
    two = GroundQuery(Answer.yes, (parse_term("a"), parse_term("b")))
    assert classify(two) is QueryForm.CONJUNCTIVE_GROUND
