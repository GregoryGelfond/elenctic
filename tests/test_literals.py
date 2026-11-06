import pytest
from clingo import Function, Number, String, parse_term
from hypothesis import given
from hypothesis import strategies as st

from elenctic.literals import Literal
from elenctic.patterns import Pattern
from elenctic.terms import Compound, Variable

X, Y = Variable("X"), Variable("Y")


def lit(text: str) -> Literal:
    return Literal.of(parse_term(text))


names = st.sampled_from(["p", "q", "r_1"])
terms = st.one_of(
    st.integers(-5, 5).map(Number),
    st.sampled_from(["a", "b", "c"]).map(lambda n: Function(n, [])),
    st.text("xyz,= ", max_size=3).map(String),
)
literals = st.builds(Literal, names, st.lists(terms, max_size=3).map(tuple), st.booleans())


@given(literals)
def test_the_contrary_of_the_contrary_is_the_literal(literal: Literal) -> None:
    assert literal.contrary.contrary == literal
    assert literal.contrary != literal


@given(literals)
def test_a_literal_survives_the_round_trip_through_a_clingo_symbol(literal: Literal) -> None:
    assert Literal.of(literal.symbol) == literal


def test_a_literal_prints_as_the_asp_it_stands_for() -> None:
    assert str(lit('-p(1,"a,b",c)')) == '-p(1,"a,b",c)'
    assert str(lit("q")) == "q"


def test_only_a_function_symbol_is_a_literal() -> None:
    with pytest.raises(ValueError, match="not a literal"):
        Literal.of(Number(1))


def test_a_pattern_has_its_distinct_named_variables_in_order_of_first_occurrence() -> None:
    assert Pattern("p", (Y, parse_term("a"), X, Y)).variables == (Y, X)
    assert Pattern("p", (Variable("_"), X, Variable("_"))).variables == (X,)


def test_a_pattern_knows_whether_an_anonymous_variable_is_beneath_any_argument() -> None:
    nested = Pattern("p", (X, Compound("f", (parse_term("a"), Variable("_")))))
    assert nested.anonymous
    assert not Pattern("p", (X, Compound("f", (Y,)), parse_term("a"))).anonymous
    assert not Pattern("p", ()).anonymous


def test_the_contrary_of_a_pattern_flips_its_sign() -> None:
    assert Pattern("p", (X,)).contrary == Pattern("p", (X,), positive=False)


@pytest.mark.parametrize("text", ["p", "-p", 'p(1,"a=b")', "-p(q(2),x)"])
def test_a_literal_is_read_back_from_its_text(text: str) -> None:
    assert str(Literal.parse(text)) == text


@pytest.mark.parametrize("text", ["1", '"s"', "p(", "(1,2)"])
def test_text_that_is_not_a_literal_is_a_value_error(text: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        Literal.parse(text)
