import pytest
from clingo import Number, String, parse_term

from aspnext.literals import Pattern, Variable
from aspnext.spans import Diagnostic, Position, Span
from aspnext.syntax import Item, read_bindings, read_literals

WHERE = Span("c.lp", Position(7, 12), Position(7, 40))
X = Variable("X")


def items(text: str) -> tuple[Item, ...]:
    found = read_literals(text, WHERE)
    assert not isinstance(found, Diagnostic), found
    return found


def test_a_list_of_literals_reads_with_strong_negation_and_default_negation() -> None:
    first, second, third = items('p(X,"a,b"), -q(1), not r')
    assert first.pattern == Pattern("p", (X, String("a,b")))
    assert second.pattern == Pattern("q", (Number(1),), positive=False)
    assert (first.negated, second.negated, third.negated) == (False, False, True)


def test_a_ground_function_term_is_one_argument() -> None:
    (item,) = items("p(d(1,2))")
    assert item.pattern.arguments == (parse_term("d(1,2)"),)


def test_each_item_knows_its_place_in_the_enclosing_source() -> None:
    first, second = items("p, q")
    assert first.span == Span("c.lp", Position(7, 12), Position(7, 13))
    assert second.span == Span("c.lp", Position(7, 15), Position(7, 16))


def test_a_later_line_keeps_its_own_columns() -> None:
    (_, second) = items("p,\n  q")
    assert second.span == Span("c.lp", Position(8, 3), Position(8, 4))


@pytest.mark.parametrize(
    "text",
    ["p(", "p. q", "X < 2", "p(1..3)", "p(f(X))", "not not p", "#true", "p(1;2)", "{ p }"],
)
def test_what_is_not_a_literal_list_is_a_diagnostic_in_the_enclosing_source(text: str) -> None:
    found = read_literals(text, WHERE)
    assert isinstance(found, Diagnostic)
    assert found.span.source == "c.lp"
    assert found.span.start.line >= 7


def test_a_syntax_error_is_placed_where_it_was_written() -> None:
    found = read_literals("p(1,\n  ;", WHERE)
    assert isinstance(found, Diagnostic)
    assert found.span.start == Position(8, 3)


def test_bindings_of_one_variable_are_bare_terms() -> None:
    assert read_bindings("a, 2", 1, WHERE) == ((parse_term("a"),), (Number(2),))


def test_bindings_of_several_variables_are_tuples() -> None:
    expected = ((parse_term("a"), Number(1)), (parse_term("b"), Number(2)))
    assert read_bindings("(a,1), (b,2)", 2, WHERE) == expected


def test_a_lone_tuple_of_several_variables_is_still_one_binding() -> None:
    assert read_bindings("(a,1)", 2, WHERE) == ((parse_term("a"), Number(1)),)


def test_no_bindings_is_the_empty_set() -> None:
    assert read_bindings("", 2, WHERE) == ()


@pytest.mark.parametrize("text", ["(a,1,3)", "a", "(", "X"])
def test_bindings_of_the_wrong_arity_or_shape_are_a_diagnostic(text: str) -> None:
    assert isinstance(read_bindings(text, 2, WHERE), Diagnostic)
