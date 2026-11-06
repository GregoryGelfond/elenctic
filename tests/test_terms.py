import pytest
from clingo import Function, Number, String, parse_term

from elenctic.substitution import Substitution
from elenctic.terms import (
    Compound,
    Variable,
    build,
    leaves,
    rename,
    render,
    substitute_with,
    variables,
)

X, Y, Z = Variable("X"), Variable("Y"), Variable("Z")
A = parse_term("a")


def nested(depth: int, leaf: Variable | Compound = X) -> Compound:
    term = Compound("f", (leaf,))
    for _ in range(depth - 1):
        term = Compound("f", (term,))
    return term


def test_a_term_without_variables_is_the_symbol_it_denotes() -> None:
    assert build("f", [A, Number(1)]) == Function("f", [A, Number(1)])


def test_a_term_with_a_variable_beneath_it_is_a_compound() -> None:
    assert build("f", [A, X]) == Compound("f", (A, X))


def test_the_sign_of_a_function_is_kept() -> None:
    assert build("f", [X], positive=False) == Compound("f", (X,), positive=False)
    assert build("f", [A], positive=False) == Function("f", [A], positive=False)


def test_a_compound_with_only_ground_arguments_is_refused() -> None:
    with pytest.raises(ValueError, match="only ground arguments"):
        Compound("f", (A,))


def test_compounds_are_equal_when_their_shapes_and_leaves_agree() -> None:
    assert Compound("f", (X, A)) == Compound("f", (X, A))
    assert hash(Compound("f", (X, A))) == hash(Compound("f", (X, A)))


@pytest.mark.parametrize(
    "other",
    [
        Compound("g", (X, A)),
        Compound("f", (Y, A)),
        Compound("f", (X, A), positive=False),
        Compound("f", (X, Compound("g", (X,)))),
        Compound("f", (X, Number(1))),
    ],
)
def test_compounds_differ_by_functor_variable_sign_or_argument(other: Compound) -> None:
    assert Compound("f", (X, A)) != other


def test_a_compound_is_never_a_variable_or_a_symbol() -> None:
    assert Compound("f", (X,)) != X
    assert Compound("f", (X,)) != Function("f", [Number(1)])


def test_compounds_nested_far_deeper_than_the_interpreter_allows_compare_and_hash() -> None:
    depth = 100_000
    left, right = nested(depth), nested(depth)
    assert left == right
    assert hash(left) == hash(right)
    assert left != nested(depth, Y)
    assert left != nested(depth + 1)
    assert len(render(left)) == 3 * depth + 1


def test_the_leaves_of_a_term_are_its_symbols_and_variables_in_order() -> None:
    term = Compound("f", (X, Compound("g", (A, Y)), Number(2)))
    assert list(leaves(term)) == [X, A, Y, Number(2)]


def test_the_variables_of_a_term_are_distinct_named_and_in_order_of_first_occurrence() -> None:
    term = Compound("f", (Y, Compound("g", (X, Variable("_"), Y)), X))
    assert variables(term) == (Y, X)
    assert variables(A) == ()


def test_a_substitution_is_followed_through_the_terms_it_introduces() -> None:
    bindings = Substitution({X: Compound("g", (Y,)), Y: Z, Z: A})
    assert substitute_with(Compound("f", (X, Y)), bindings.get) == Function(
        "f", [Function("g", [A]), A]
    )


def test_a_variable_the_substitution_leaves_free_stays() -> None:
    assert substitute_with(Compound("f", (X, Y)), Substitution({X: A}).get) == Compound("f", (A, Y))


def test_substituting_into_a_term_nested_very_deeply_needs_no_recursion() -> None:
    result = substitute_with(nested(100_000), Substitution({X: A}).get)
    assert isinstance(result, type(A))
    assert result.type is A.type


def test_renaming_replaces_each_variable_once_even_by_a_name_it_also_renames() -> None:
    renamed = rename(Compound("f", (X, Y, X)), lambda v: {X: Y, Y: Z}[v])
    assert renamed == Compound("f", (Y, Z, Y))


def test_a_term_is_written_as_the_program_would() -> None:
    term = Compound(
        "f", (X, Compound("g", (A, Y), positive=False), String("s"), Compound("", (X, Y)))
    )
    assert render(term) == 'f(X,-g(a,Y),"s",(X,Y))'


def test_a_compound_and_a_substitution_are_written_as_the_terms_they_hold() -> None:
    term = Compound("f", (Variable("X"), Number(2)))
    assert (str(term), repr(term)) == ("f(X,2)", "Compound(f(X,2))")
    assert str(Substitution({Variable("X"): term, Variable("Y"): Number(1)})) == "{X=f(X,2), Y=1}"


def test_a_one_element_tuple_keeps_its_trailing_comma() -> None:
    assert render(Compound("", (X,))) == "(X,)"
