import pytest
from clingo import Function, Number, String, parse_term
from hypothesis import given
from hypothesis import strategies as st

from elenctic.extension import Extension
from elenctic.literals import Literal
from elenctic.patterns import Pattern
from elenctic.terms import Variable

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


def test_a_pattern_binds_its_distinct_variables_in_order_of_first_occurrence() -> None:
    pattern = Pattern("p", (Y, parse_term("a"), X, Y))
    assert pattern.variables == (Y, X)
    assert pattern.match(lit("p(1,a,2,1)")) == (Number(1), Number(2))


def test_a_repeated_variable_must_take_one_value() -> None:
    assert Pattern("p", (X, X)).match(lit("p(1,2)")) is None
    assert Pattern("p", (X, X)).match(lit("p(1,1)")) == (Number(1),)


@pytest.mark.parametrize(
    ("text", "matches"),
    [("p(1)", True), ("q(1)", False), ("-p(1)", False), ("p(1,2)", False), ("p(2)", False)],
)
def test_a_pattern_matches_only_its_own_signature_and_ground_arguments(
    text: str, *, matches: bool
) -> None:
    assert (Pattern("p", (Number(1),)).match(lit(text)) is not None) is matches


def test_a_string_argument_with_separators_is_one_argument() -> None:
    pattern = Pattern("p", (X, String("a,b")))
    assert pattern.match(Literal("p", (Number(1), String("a,b")))) == (Number(1),)


def test_an_anonymous_variable_binds_nothing_and_matches_anything() -> None:
    pattern = Pattern("p", (Variable("_"), X, Variable("_")))
    assert pattern.variables == (X,)
    assert pattern.match(lit("p(1,2,3)")) == (Number(2),)


def test_the_contrary_of_a_pattern_flips_its_sign() -> None:
    assert Pattern("p", (X,)).contrary == Pattern("p", (X,), positive=False)


def test_the_bindings_of_a_pattern_in_a_set_of_literals_are_those_of_its_matches() -> None:
    atoms = {lit("p(1,a)"), lit("p(2,a)"), lit("p(3,b)"), lit("q(9,a)")}
    pattern = Pattern("p", (X, parse_term("a")))
    assert pattern.bindings_in(Extension(atoms)) == {(Number(1),), (Number(2),)}


@pytest.mark.parametrize("text", ["p", "-p", 'p(1,"a=b")', "-p(q(2),x)"])
def test_a_literal_is_read_back_from_its_text(text: str) -> None:
    assert str(Literal.parse(text)) == text


@pytest.mark.parametrize("text", ["1", '"s"', "p(", "(1,2)"])
def test_text_that_is_not_a_literal_is_a_value_error(text: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        Literal.parse(text)
