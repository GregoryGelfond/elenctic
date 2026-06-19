import pytest
from clingo import parse_term

from elenctic.query import Answer, BindingQuery, GroundQuery, QueryLiteral, Var, parse_query


@pytest.mark.parametrize(
    ("answer", "payload", "expected"),
    [
        pytest.param(
            "yes",
            "{ start(s), end(t) }",
            GroundQuery(Answer.yes, (parse_term("start(s)"), parse_term("end(t)"))),
            id="ground-conjunctive",
        ),
        pytest.param(
            "no",
            "{ reachable(x) }",
            GroundQuery(Answer.no, (parse_term("reachable(x)"),)),
            id="ground-single",
        ),
    ],
)
def test_parse_ground_query(answer: str, payload: str, expected: GroundQuery) -> None:
    assert parse_query(answer, payload) == expected


def test_parse_binding_query_one_arg() -> None:
    q = parse_query("yes", "{ reachable(X) } = { s, a, t }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("reachable", True, (Var("X"),))
    assert q.goal.variables == ("X",)
    assert q.bindings == frozenset({(parse_term("s"),), (parse_term("a"),), (parse_term("t"),)})


def test_parse_binding_query_two_arg() -> None:
    q = parse_query("yes", "{ edge(X, Y) } = { (s, a), (a, t) }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("edge", True, (Var("X"), Var("Y")))
    assert q.goal.variables == ("X", "Y")
    assert q.bindings == frozenset(
        {(parse_term("s"), parse_term("a")), (parse_term("a"), parse_term("t"))}
    )


def test_parse_binding_query_repeated_variable_collapses_to_one_column() -> None:
    # Def 2.2.2: "the list of variables occurring in q" is distinct → q(X, X) has arity 1.
    q = parse_query("yes", "{ rel(X, X) } = { a, b }")
    assert isinstance(q, BindingQuery)
    assert q.goal.variables == ("X",)
    assert q.bindings == frozenset({(parse_term("a"),), (parse_term("b"),)})


def test_parse_binding_query_strong_negation_goal() -> None:
    q = parse_query("yes", "{ -blocked(X) } = { a }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("blocked", False, (Var("X"),))


@pytest.mark.parametrize(
    ("answer", "payload", "match"),
    [
        pytest.param("maybe", "{ a }", "yes|no|unknown", id="bad-answer"),
        pytest.param(
            "yes", "{ path(X, a, Y) } = { (s, t) }", "all-variable", id="partially-ground"
        ),
        pytest.param("yes", "a, b", "brace set", id="missing-braces"),
    ],
)
def test_parse_query_rejects(answer: str, payload: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_query(answer, payload)
