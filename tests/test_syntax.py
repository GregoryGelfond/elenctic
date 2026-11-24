import pytest
from clingo import Number, String, Symbol, parse_term
from hypothesis import given, settings
from hypothesis import strategies as st

from elenctic.determination import Valuation
from elenctic.literals import Assumption, Literal
from elenctic.patterns import Pattern
from elenctic.queries import read_query
from elenctic.query import All, Not
from elenctic.rows import read_bindings
from elenctic.spans import Diagnostic, Position, Span
from elenctic.syntax import (
    Item,
    asked,
    read_asked,
    read_binding,
    read_literals,
    read_scenario,
    read_valuations,
)
from elenctic.terms import Compound, Variable
from elenctic.writer import queried
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


def test_a_syntax_error_in_a_list_is_placed_in_characters_after_non_ascii_text() -> None:
    found = read_literals('p("é"), )', WHERE)
    assert isinstance(found, Diagnostic)
    assert found.span == Span("c.lp", Position(7, 20), Position(7, 21))


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


def test_a_query_with_variables_is_a_conjunction_of_its_parts_as_written() -> None:
    reach, closed = Pattern("reach", (X,)), Pattern("closed", (X,))
    assert read_query("reach(X), not closed(X)", "QUERY") == All((reach, Not(closed)))
    assert read_query("{ not closed(X), reach(X), q }", "QUERY") == All(
        (Not(closed), reach, Literal("q"))
    )


def test_a_query_reads_not_as_default_negation_of_the_literal_after_it() -> None:
    assert read_query("{ a, not -b }", "QUERY") == All(
        (Literal("a"), Not(Literal("b", positive=False)))
    )
    assert read_query("not a", "QUERY") == All((Not(Literal("a")),))


@pytest.mark.parametrize("text", ["reach(b).", "{ reach(b) }.", " reach(b) . "])
def test_a_query_may_end_with_a_full_stop(text: str) -> None:
    assert read_query(text, "QUERY") == All((Literal("reach", (parse_term("b"),)),))


@pytest.mark.parametrize(
    ("text", "column"), [("a; b", 2), ("{ a, b ; c }", 8), ("a;", 2), ("p(1); q", 5)]
)
def test_a_semicolon_between_literals_is_refused_where_it_stands(text: str, column: int) -> None:
    refused = read_query(text, "QUERY")
    assert isinstance(refused, Diagnostic)
    assert refused.message == "query uses a semicolon"
    assert refused.span == Span("QUERY", Position(1, column), Position(1, column + 1))
    assert [child.message for child in refused.children] == ["separate the literals with `,`"]


def test_a_semicolon_in_a_pool_is_refused_as_the_pool_not_as_a_separator() -> None:
    refused = read_query("p(a, (b;c))", "QUERY")
    assert isinstance(refused, Diagnostic)
    assert (refused.message, refused.label) == (
        "`(b;c)` is not a pattern",
        "a pool stands for several terms",
    )


def test_a_semicolon_on_a_later_line_is_refused_where_it_stands() -> None:
    refused = read_query("a,\n b; c", "QUERY")
    assert isinstance(refused, Diagnostic)
    assert refused.span == Span("QUERY", Position(2, 3), Position(2, 4))


def test_a_semicolon_inside_a_string_is_part_of_the_string() -> None:
    assert read_query('p("x;y")', "QUERY") == All((Literal("p", (String("x;y"),)),))


@pytest.mark.parametrize("text", ["a..", "a,", "{ a, }", "p(", "{ a :- }"])
def test_a_syntax_error_in_a_query_is_placed_within_what_was_written(text: str) -> None:
    refused = read_query(text, "QUERY")
    assert isinstance(refused, Diagnostic)
    assert refused.span is not None
    assert refused.span.start.line == refused.span.end.line == 1
    assert 1 <= refused.span.start.column < refused.span.end.column <= len(text) + 1


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{ not not a }", "expected a literal"),
        ("{ not p(X) }", "variable `X` occurs only under `not`"),
        ("{ p(X), not q(X, Y) }", "variable `Y` occurs only under `not`"),
        ("{ p(X), q(_) }", "anonymous variable"),
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


def test_what_a_command_was_given_is_placed_inside_its_braces_and_before_its_full_stop() -> None:
    placed = asked(" { p(1) }. ", "QUERY")
    assert placed.text == " p(1) "
    assert placed.at == Span("QUERY", Position(1, 3), Position(1, 9))
    assert placed.whole == Span("QUERY", Position(1, 1), Position(1, 12))


def test_a_ground_query_is_written_with_not_after_the_literal_without_it() -> None:
    p, q = Literal("p"), Literal("q")
    assert queried(All((Not(p), q, p))) == "{ p, not p, q }"


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [("a,\n p(", Position(2, 3), Position(2, 4)), ("{ a,\n}", Position(2, 1), Position(2, 1))],
)
def test_a_syntax_error_past_a_later_line_is_placed_at_its_end(
    text: str, start: Position, end: Position
) -> None:
    refused = read_query(text, "QUERY")
    assert isinstance(refused, Diagnostic)
    assert refused.span == Span("QUERY", start, end)


def test_a_binding_reads_as_ask_writes_it_in_the_order_of_the_variables() -> None:
    assert read_binding('Y = "a,b", X = f(1)', ("X", "Y"), "--binding") == (
        parse_term("f(1)"),
        String("a,b"),
    )
    assert read_binding("{ X = -3 }.", ("X",), "--binding") == (Number(-3),)


@pytest.mark.parametrize(
    ("text", "message", "column"),
    [
        ("X = 1, p(Y)", "expected `variable = term`, found `p(Y)`", 8),
        ("X = Z", "expected `variable = term`, found `X = Z`", 1),
        ("X < 1", "expected `variable = term`, found `X < 1`", 1),
        ("X = 1, Z = 2", "`Z` is not a variable of the query", 8),
        ("X = 1, X = 2", "`X` is bound twice", 8),
    ],
)
def test_a_binding_that_is_not_one_value_for_each_variable_is_refused_where_it_stands(
    text: str, message: str, column: int
) -> None:
    refused = read_binding(text, ("X", "Y"), "--binding")
    assert isinstance(refused, Diagnostic)
    assert refused.message == message
    assert refused.span is not None
    assert (refused.span.source, refused.span.start.column) == ("--binding", column)


def test_a_binding_without_a_value_for_some_variable_is_refused_naming_it() -> None:
    refused = read_binding("Y = 1", ("X", "Y"), "--binding")
    assert isinstance(refused, Diagnostic)
    assert refused.message == "the binding gives `X` no value"
    assert [child.message for child in refused.children] == [
        "bind each of the query's variables: `X = …, Y = …`"
    ]
