import pytest
from clingo import Number, String, Symbol, parse_term
from hypothesis import given, settings
from hypothesis import strategies as st

from elenctic.determination import Valuation
from elenctic.literals import Assumption, Literal
from elenctic.patterns import Pattern
from elenctic.queries import read_query
from elenctic.query import All
from elenctic.rows import read_bindings
from elenctic.spans import Diagnostic, Position, Span
from elenctic.syntax import Item, read_asked, read_literals, read_scenario, read_valuations
from elenctic.terms import Compound, Variable
from elenctic.writer import rows as rows_written

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


def test_a_term_with_a_variable_beneath_a_function_is_part_of_a_pattern() -> None:
    (item,) = items("-p(f(g(X),1+1),(Y,a),_)")
    assert item.pattern == Pattern(
        "p",
        (
            Compound("f", (Compound("g", (X,)), Number(2))),
            Compound("", (Variable("Y"), parse_term("a"))),
            Variable("_"),
        ),
        positive=False,
    )


@pytest.mark.parametrize(
    ("text", "message", "label"),
    [
        ("p(1..3)", "`(1..3)` is not a pattern", "an interval stands for several terms"),
        ("p(a, (b;c))", "`(b;c)` is not a pattern", "a pool stands for several terms"),
        (
            "p(f(@g(X)))",
            "`@g(X)` is not a pattern",
            "a call to an external function is not made",
        ),
        (
            "p(X+1)",
            "`(X+1)` is not a pattern",
            "arithmetic over a variable or undefined has no value",
        ),
    ],
)
def test_a_term_that_is_no_pattern_is_refused_with_the_reason_not_read_as_a_mismatch(
    text: str, message: str, label: str
) -> None:
    found = read_literals(text, WHERE)
    assert isinstance(found, Diagnostic)
    assert (found.message, found.label) == (message, label)


def test_each_item_knows_its_place_in_the_enclosing_source() -> None:
    first, second = items("p, q")
    assert first.span == Span("c.lp", Position(7, 12), Position(7, 13))
    assert second.span == Span("c.lp", Position(7, 15), Position(7, 16))


def test_a_later_line_keeps_its_own_columns() -> None:
    (_, second) = items("p,\n  q")
    assert second.span == Span("c.lp", Position(8, 3), Position(8, 4))


@pytest.mark.parametrize(
    "text",
    [
        "p(",
        "p. q",
        "X < 2",
        "p(1..3)",
        "not not p",
        "#true",
        "p(1;2)",
        "{ p }",
        "1",
        "~p",
        "|p|",
    ],
)
def test_what_is_not_a_literal_list_is_a_diagnostic_in_the_enclosing_source(text: str) -> None:
    found = read_literals(text, WHERE)
    assert isinstance(found, Diagnostic)
    assert found.span is not None
    assert found.span.source == "c.lp"
    assert found.span.start.line >= 7


def test_a_syntax_error_is_placed_where_it_was_written() -> None:
    found = read_literals("p(1,\n  ;", WHERE)
    assert isinstance(found, Diagnostic)
    assert found.span is not None
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


def test_several_variables_need_a_tuple_even_for_one_binding() -> None:
    assert isinstance(read_bindings("a, 1", 2, WHERE), Diagnostic)


def test_rows_of_the_right_arity_are_each_a_binding() -> None:
    assert read_bindings("(1,2), (3,4)", 2, WHERE) == (
        (Number(1), Number(2)),
        (Number(3), Number(4)),
    )


def test_a_row_mixed_with_a_bare_term_is_a_diagnostic() -> None:
    assert isinstance(read_bindings("(1,2), 3", 2, WHERE), Diagnostic)


def test_a_tuple_valued_binding_of_one_variable_is_one_element() -> None:
    """`{ (1,2) }` is one binding whose term is the tuple, not two bindings 1 and 2."""
    assert read_bindings("(1,2)", 1, WHERE) == ((parse_term("(1,2)"),),)


def test_a_nested_tuple_component_of_an_n_ary_binding_is_kept() -> None:
    assert read_bindings("((1,2),3)", 2, WHERE) == ((parse_term("(1,2)"), Number(3)),)


def test_valuations_read_a_term_and_the_integer_it_equals() -> None:
    found = read_valuations("start(t1)=3, x = -2, f(a,b)=0", WHERE)
    assert found == (
        Valuation(parse_term("start(t1)"), 3),
        Valuation(parse_term("x"), -2),
        Valuation(parse_term("f(a,b)"), 0),
    )


def test_a_refused_valuation_is_placed_in_characters_after_non_ascii_text() -> None:
    found = read_valuations('x("é") = 1, y("é")', WHERE)
    assert isinstance(found, Diagnostic)
    assert found.span == Span("c.lp", Position(7, 24), Position(7, 30))


@pytest.mark.parametrize(
    ("text", "start"),
    [
        ("x=a", Position(7, 12)),
        ("X=3", Position(7, 12)),
        ("not x=3", Position(7, 12)),
        ("x<3", Position(7, 12)),
        ("1<x<3", Position(7, 12)),
        ("x=1, y", Position(7, 17)),
    ],
)
def test_a_valuation_that_is_not_a_term_equal_to_an_integer_is_a_diagnostic(
    text: str, start: Position
) -> None:
    found = read_valuations(text, WHERE)
    assert isinstance(found, Diagnostic)
    assert found.message.startswith("expected `term = integer`, found `")
    assert found.span is not None
    assert found.span.start == start


def test_a_valuation_list_that_does_not_parse_is_a_diagnostic() -> None:
    assert isinstance(read_valuations("x=", WHERE), Diagnostic)


def _written(rows: tuple[tuple[Symbol, ...], ...], arity: int) -> str:
    """Write rows with the writer claims and details use, without the braces around them."""
    pattern = Pattern("p", tuple(Variable(f"V{at}") for at in range(arity)))
    return rows_written(pattern, frozenset(rows)).removeprefix("{").removesuffix("}").strip()


@given(st.lists(st.integers(min_value=-5, max_value=5), min_size=0, max_size=4))
@settings(max_examples=30)
def test_one_variable_bindings_round_trip_through_the_reader(values: list[int]) -> None:
    rows = tuple((Number(v),) for v in values)
    assert read_bindings(_written(rows, 1), 1, WHERE) == tuple(sorted(set(rows)))


@given(
    st.lists(
        st.tuples(st.integers(min_value=-3, max_value=3), st.integers(min_value=-3, max_value=3)),
        min_size=0,
        max_size=3,
    )
)
@settings(max_examples=30)
def test_two_variable_bindings_round_trip_through_the_reader(
    pairs: list[tuple[int, int]],
) -> None:
    rows = tuple((Number(a), Number(b)) for a, b in pairs)
    assert read_bindings(_written(rows, 2), 2, WHERE) == tuple(sorted(set(rows)))


def test_a_tuple_valued_one_variable_binding_round_trips() -> None:
    row = ((parse_term("(1,2)"),),)
    assert read_bindings(_written(row, 1), 1, WHERE) == row


# What a command asks: an atom, a query, assumptions, written on the command line.


def test_an_atom_asked_about_reads_with_or_without_default_negation() -> None:
    reach = Literal("reach", (parse_term("c"),))
    assert read_asked("reach(c)", "ATOM") == (reach, False)
    assert read_asked("not reach(c)", "ATOM") == (reach, True)
    assert read_asked("-p", "ATOM") == (Literal("p", positive=False), False)
    assert read_asked("not -p", "ATOM") == (Literal("p", positive=False), True)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("p(X)", "atom asked about is not ground"),
        ("p, q", "expected one atom, found `p, q`"),
        ("", "expected one atom, found nothing"),
        ("p :- q", "syntax error"),
        ("X < 2", "expected a literal"),
    ],
)
def test_an_atom_that_is_not_one_ground_literal_is_refused(text: str, message: str) -> None:
    refused = read_asked(text, "ATOM")
    assert isinstance(refused, Diagnostic)
    assert message in refused.message
    assert refused.span is not None
    assert refused.span.source == "ATOM"


def test_assumptions_read_as_a_scenario_with_or_without_braces() -> None:
    expected = frozenset({Assumption(Literal("a")), Assumption(Literal("b"), holds=False)})
    assert read_scenario("a, not b", "--assuming") == expected
    assert read_scenario("{ a, not b }", "--assuming") == expected


def test_an_assumption_with_a_variable_is_refused() -> None:
    refused = read_scenario("p(X)", "--assuming")
    assert isinstance(refused, Diagnostic)
    assert "assumption is not ground" in refused.message


def test_a_query_reads_as_the_query_tag_reads_it() -> None:
    assert read_query("{ a, -b }", "QUERY") == All((Literal("a"), Literal("b", positive=False)))
    assert read_query("a", "QUERY") == All((Literal("a"),))
    assert read_query("{ p(X, 1) }", "QUERY") == Pattern("p", (X, Number(1)))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{ not a }", "query uses `not`"),
        ("{ p(X), q }", "query with variables has one pattern"),
        ("{ p(_) }", "anonymous variable"),
        ("{ }", "expected at least one atom"),
    ],
)
def test_a_query_the_query_tag_would_refuse_is_refused(text: str, message: str) -> None:
    refused = read_query(text, "QUERY")
    assert isinstance(refused, Diagnostic)
    assert message in refused.message


@pytest.mark.parametrize("text", ["{ ab", "ab }"])
def test_a_brace_left_open_is_not_taken_for_braces(text: str) -> None:
    assert isinstance(read_query(text, "QUERY"), Diagnostic)
