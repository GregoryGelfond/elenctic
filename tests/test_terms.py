import pytest
from clingo import Function, Number, parse_term

from elenctic.terms import contrary, parse_litset, parse_tupleset


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        pytest.param("start(s)", ("start(s)",), id="singleton"),
        pytest.param(
            "included(s,a,2,1), start(s)",
            ("included(s,a,2,1)", "start(s)"),
            id="multi-paren-aware",
        ),
        pytest.param("-reachable(x)", ("-reachable(x)",), id="strong-negation"),
    ],
)
def test_parse_litset(body: str, expected: tuple[str, ...]) -> None:
    assert parse_litset(body) == tuple(parse_term(atom) for atom in expected)


@pytest.mark.parametrize(
    ("body", "arity", "expected"),
    [
        pytest.param("s, a, t", 1, (("s",), ("a",), ("t",)), id="one-arg-bare-terms"),
        pytest.param("(s,1), (a,2)", 2, (("s", "1"), ("a", "2")), id="n-arg-tuples"),
        pytest.param("(s,1)", 2, (("s", "1"),), id="singleton-n-tuple"),
        pytest.param("", 1, (), id="empty"),
    ],
)
def test_parse_tupleset(body: str, arity: int, expected: tuple[tuple[str, ...], ...]) -> None:
    assert parse_tupleset(body, arity) == tuple(
        tuple(parse_term(term) for term in tup) for tup in expected
    )


def test_parse_tupleset_rejects_arity_mismatch() -> None:
    with pytest.raises(ValueError, match="arity 2"):
        parse_tupleset("(s, t), (a)", arity=2)


def test_contrary_flips_strong_negation() -> None:
    atom = Function("a")
    assert contrary(atom) == Function("a", [], False)
    assert contrary(contrary(atom)) == atom  # l̄̄ = l


def test_contrary_rejects_non_literal() -> None:
    with pytest.raises(ValueError, match="not a literal"):
        contrary(Number(1))
