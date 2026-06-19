import pytest
from clingo import parse_term

from elenctic.query import Answer, BindingQuery, GroundQuery, QueryLiteral, Var, parse_query


def test_parse_ground_conjunctive_query() -> None:
    q = parse_query("yes", "{ start(s), end(t) }")
    assert isinstance(q, GroundQuery)
    assert q.answer is Answer.yes
    assert q.conjuncts == (parse_term("start(s)"), parse_term("end(t)"))


def test_parse_ground_single_literal_query() -> None:
    q = parse_query("no", "{ reachable(x) }")
    assert isinstance(q, GroundQuery)
    assert q.answer is Answer.no
    assert q.conjuncts == (parse_term("reachable(x)"),)


def test_parse_binding_query_one_arg() -> None:
    q = parse_query("yes", "{ reachable(X) } = { s, a, t }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("reachable", True, (Var("X"),))
    assert q.bindings == frozenset({(parse_term("s"),), (parse_term("a"),), (parse_term("t"),)})


def test_parse_binding_query_two_arg_all_variable() -> None:
    q = parse_query("yes", "{ edge(X, Y) } = { (s, a), (a, t) }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("edge", True, (Var("X"), Var("Y")))
    assert q.goal.variables == ("X", "Y")
    assert q.bindings == frozenset(
        {(parse_term("s"), parse_term("a")), (parse_term("a"), parse_term("t"))}
    )


def test_parse_binding_query_repeated_variable_has_distinct_var_arity() -> None:
    # Def 2.2.2: X1,…,Xn is the list of *distinct* variables occurring in q.
    # rel(X, X) has one variable, so the binding tuples have arity 1.
    q = parse_query("yes", "{ rel(X, X) } = { a, b }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("rel", True, (Var("X"), Var("X")))
    assert q.goal.variables == ("X",)
    assert q.bindings == frozenset({(parse_term("a"),), (parse_term("b"),)})


def test_parse_binding_query_strong_negation_goal() -> None:
    q = parse_query("yes", "{ -blocked(X) } = { a }")
    assert isinstance(q, BindingQuery)
    assert q.goal == QueryLiteral("blocked", False, (Var("X"),))


def test_parse_binding_query_rejects_partially_ground_goal() -> None:
    # v1 adheres to Def 2.2.2: binding goals are all-variable; ground args → §11.
    with pytest.raises(ValueError):
        parse_query("yes", "{ path(X, a, Y) } = { (s, t) }")


def test_parse_query_rejects_bad_answer() -> None:
    with pytest.raises(ValueError):
        parse_query("maybe", "{ a }")
