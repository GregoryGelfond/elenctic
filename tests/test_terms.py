"""Parsing the term-level payloads a contract carries — literal sets and tuple sets — and taking
the contrary of a literal, together with what each refuses and the quoting it must survive."""

import pytest
from clingo import Function, Number, parse_term

from elenctic.terms import contrary, parse_litset, parse_tupleset, signature_of


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


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace-only"),
        pytest.param("foo, 1", id="non-literal-number"),
        pytest.param('"a string"', id="non-literal-string"),
        pytest.param("reachable(X)", id="variable-not-ground"),
    ],
)
def test_parse_litset_rejects(body: str) -> None:
    # Matched loosely on purpose: these five bodies fail for three different reasons and say so in
    # three different sentences. What the match holds is that the diagnostic is about the litset —
    # a bare `ValueError` here would be satisfied by one raised anywhere underneath, including by
    # clingo's own parser for a reason that has nothing to do with what is being rejected.
    with pytest.raises(ValueError, match=r"literal set|litset"):
        parse_litset(body)


def test_parse_litset_preserves_quoted_comma() -> None:
    # The headline robustness claim: a comma inside a quoted string is one atom (clingo parses it).
    assert parse_litset('p("a,b")') == (parse_term('p("a,b")'),)


def test_a_blank_litset_body_is_refused() -> None:
    # A claim over no literals is vacuous, which is a PASS the corpus did not ask for.
    with pytest.raises(ValueError, match=r"^empty literal set: a litset needs"):
        parse_litset("")


def test_a_litset_body_that_parses_to_no_literals_is_refused() -> None:
    # The second of the two, and the one a blank-text guard cannot catch: `{ () }` is not blank, so
    # it reaches the parser, and the empty tuple then flattens to no literals at all. Asserted
    # against the whole opening of the message rather than the phrase both refusals share — written
    # the loose way, this test passes on the blank-body guard above and says nothing about this one.
    with pytest.raises(ValueError, match=r"^empty literal set \{\(\)\}: it parses to no literals"):
        parse_litset("()")


def test_a_term_that_is_not_a_literal_has_no_signature() -> None:
    # `#show` names a predicate, and a number names none. Asked of a non-function symbol, this
    # refuses rather than inventing a signature no `#show` could ever declare.
    with pytest.raises(ValueError, match="not a literal"):
        signature_of(Number(42))
