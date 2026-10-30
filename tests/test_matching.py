import pytest
from clingo import Function, Number, Symbol, parse_term

from elenctic.matching import match
from elenctic.terms import Compound, Term, Variable

X, Y, ANY = Variable("X"), Variable("Y"), Variable("_")


def sym(text: str) -> Symbol:
    return parse_term(text)


def test_a_variable_takes_the_symbol_it_faces() -> None:
    assert match([X], [sym("f(a)")]) == {X: sym("f(a)")}


def test_a_ground_pattern_matches_only_an_equal_symbol() -> None:
    assert match([sym("f(a)")], [sym("f(a)")]) == {}
    assert match([sym("f(a)")], [sym("f(b)")]) is None


def test_a_variable_repeated_must_face_one_symbol() -> None:
    assert match([X, X], [Number(1), Number(1)]) == {X: Number(1)}
    assert match([X, X], [Number(1), Number(2)]) is None


def test_a_compound_matches_a_function_of_the_same_functor_sign_and_arity() -> None:
    pattern = Compound("f", (X, sym("a")))
    assert match([pattern], [sym("f(1,a)")]) == {X: Number(1)}
    assert match([pattern], [sym("f(1,b)")]) is None
    assert match([pattern], [sym("g(1,a)")]) is None
    assert match([pattern], [sym("-f(1,a)")]) is None
    assert match([pattern], [sym("f(1,a,2)")]) is None
    assert match([pattern], [Number(1)]) is None


def test_a_tuple_pattern_matches_a_tuple() -> None:
    assert match([Compound("", (X, Y))], [sym("(1,2)")]) == {X: Number(1), Y: Number(2)}
    assert match([Compound("", (X, Y))], [sym("f(1,2)")]) is None


def test_a_variable_repeated_beneath_a_compound_must_agree_with_one_outside_it() -> None:
    pattern: list[Term] = [X, Compound("f", (Compound("g", (X,)),))]
    assert match(pattern, [Number(1), sym("f(g(1))")]) == {X: Number(1)}
    assert match(pattern, [Number(1), sym("f(g(2))")]) is None


def test_an_anonymous_variable_matches_anything_each_time() -> None:
    assert match([ANY, ANY], [Number(1), sym("f(2)")]) == {}


def test_a_symbol_that_is_not_a_function_does_not_match_a_compound() -> None:
    assert match([Compound("f", (X,))], [sym("inf")]) is None
    assert match([Compound("f", (X,))], [Function("f", [], positive=True)]) is None


def test_a_pattern_nested_very_deeply_matches_without_recursion() -> None:
    depth = 100_000
    pattern: Compound | Variable = X
    ground = Number(7)
    for _ in range(depth):
        pattern = Compound("f", (pattern,))
        ground = Function("f", [ground])
    assert match([pattern], [ground]) == {X: Number(7)}


@pytest.mark.parametrize("arity", [1, 2])
def test_matching_a_pattern_against_symbols_of_another_count_is_a_programming_error(
    arity: int,
) -> None:
    with pytest.raises(ValueError, match="argument"):
        match([X] * arity, [Number(1)] * (3 - arity))
