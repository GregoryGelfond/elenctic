import pytest
from clingo import Function, Number, parse_term

from elenctic.terms import contrary, parse_litset, parse_tupleset


def test_parse_litset_singleton() -> None:
    assert parse_litset("start(s)") == (parse_term("start(s)"),)


def test_parse_litset_multi_is_paren_aware() -> None:
    got = parse_litset("included(s,a,2,1), start(s)")
    assert got == (parse_term("included(s,a,2,1)"), parse_term("start(s)"))


def test_parse_litset_strong_negation() -> None:
    (lit,) = parse_litset("-reachable(x)")
    assert lit.name == "reachable"
    assert lit.positive is False


def test_contrary_flips_strong_negation() -> None:
    a = Function("a")
    assert contrary(a) == Function("a", [], False)
    assert contrary(contrary(a)) == a  # l̄̄ = l


def test_contrary_rejects_non_literal() -> None:
    with pytest.raises(ValueError):
        contrary(Number(1))


def test_parse_tupleset_one_arg_bare_terms() -> None:
    assert parse_tupleset("s, a, t", arity=1) == (
        (parse_term("s"),),
        (parse_term("a"),),
        (parse_term("t"),),
    )


def test_parse_tupleset_n_arg_tuples() -> None:
    assert parse_tupleset("(s,1), (a,2)", arity=2) == (
        (parse_term("s"), parse_term("1")),
        (parse_term("a"), parse_term("2")),
    )


def test_parse_tupleset_singleton_n_tuple() -> None:
    assert parse_tupleset("(s,1)", arity=2) == ((parse_term("s"), parse_term("1")),)


def test_parse_tupleset_empty() -> None:
    assert parse_tupleset("", arity=1) == ()
