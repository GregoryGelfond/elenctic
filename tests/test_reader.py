import pytest
from clingo import Number, String, parse_term

from elenctic.contract import (
    Asks,
    Assigns,
    Binds,
    Census,
    Claim,
    Contract,
    Costs,
    Entails,
    Satisfiable,
    Solver,
    Witness,
)
from elenctic.determination import Mode, Range, Valuation
from elenctic.literals import Assumption, Literal
from elenctic.patterns import Pattern
from elenctic.query import All, Answer
from elenctic.reader import parse_contract
from elenctic.spans import Diagnostic, Position, Span
from elenctic.tags import is_case
from elenctic.terms import Compound, Variable
from elenctic.writer import render

X = Variable("X")
P = Position


def parse(*lines: str) -> Contract:
    return parse_contract("\n".join(lines), "c.lp")


def only(*lines: str) -> Claim:
    contract = parse("% @expect sat", *lines)
    assert not contract.diagnostics, contract.diagnostics
    return contract.claims[1]


def messages(*lines: str) -> list[str]:
    return [d.message for d in parse(*lines).diagnostics]


def test_each_tag_reads_into_its_claim_with_the_line_it_was_written_on() -> None:
    contract = parse(
        "p. q.",
        "% @expect sat",
        "% @count 2",
        "% @cautious { p }",
        "% @brave { p, -q }",
        "% @answer-set { p, q }",
    )
    assert not contract.diagnostics
    assert [c.reading for c in contract.claims] == [
        Satisfiable(expected=True),
        Census(2),
        Entails(Mode.CAUTIOUS, frozenset({Literal("p")})),
        Entails(Mode.BRAVE, frozenset({Literal("p"), Literal("q", positive=False)})),
        Witness(frozenset({Literal("p"), Literal("q")})),
    ]
    assert [c.span.start.line for c in contract.claims] == [2, 3, 4, 5, 6]
    assert contract.claims[0].span.source == "c.lp"


def test_a_ground_query_is_a_conjunction_with_its_expected_answer() -> None:
    claim = only('% @query unknown { p(1), -q("a,b") }')
    assert claim.reading == Asks(
        Answer.UNKNOWN,
        All((Literal("p", (Number(1),)), Literal("q", (String("a,b"),), positive=False))),
    )


def test_a_binding_query_states_the_bindings_it_expects() -> None:
    claim = only("% @query yes { p(X, b) } = { 1, 2 }")
    assert claim.reading == Binds(
        Answer.YES, Pattern("p", (X, parse_term("b"))), frozenset({(Number(1),), (Number(2),)})
    )


def test_a_binding_query_may_nest_its_variables_and_keeps_their_order_of_first_occurrence() -> None:
    claim = only("% @query yes { p(f(Y, g(X)), X) } = { (1, 2) }")
    assert isinstance(claim.reading, Binds)
    assert claim.reading.pattern.variables == (Variable("Y"), X)
    assert claim.reading.pattern.arguments[0] == Compound("f", (Variable("Y"), Compound("g", (X,))))
    assert claim.reading.bindings == {(Number(1), Number(2))}


def test_a_query_whose_argument_is_an_equation_in_a_string_is_still_a_ground_query() -> None:
    claim = only('% @query yes { p("a=b") }')
    assert isinstance(claim.reading, Asks)


def test_a_scenario_follows_any_claim() -> None:
    claim = only("% @cautious { p } assuming { q, not r, -s }")
    assert claim.scenario == frozenset(
        {
            Assumption(Literal("q")),
            Assumption(Literal("r"), holds=False),
            Assumption(Literal("s", positive=False)),
        }
    )


def test_a_litset_continues_over_comment_lines_while_its_brace_is_open() -> None:
    claim = only("% @brave { p,", "%         q,", "%         r }", "% prose after the brace")
    assert isinstance(claim.reading, Entails)
    assert len(claim.reading.literals) == 3
    assert claim.span == Span("c.lp", Position(2, 3), Position(4, 14))


def test_a_brace_inside_a_string_does_not_continue_a_litset() -> None:
    contract = parse("% @expect sat", '% @brave { p("}") }', "% @count 1")
    assert [type(c.reading) for c in contract.claims] == [Satisfiable, Entails, Census]


def test_notes_and_ordinary_comments_say_nothing() -> None:
    contract = parse("% @expect sat", "% @note anything { goes", "%% not a tag @expect unsat")
    assert len(contract.claims) == 1
    assert not contract.diagnostics


def test_a_file_with_no_tag_is_a_library_not_a_case() -> None:
    assert not is_case("p.\n% just a comment\n")
    assert is_case("p.\n% @note about p\n")


def test_unknown_unsupported_and_malformed_tags_are_each_a_diagnostic_where_they_stand() -> None:
    contract = parse(
        "% @expect sat",
        "% @frobnicate { p }",
        "% @assign { x }",
        "% @count two",
        "% @cautious { }",
        "% @cautious { X }",
        "% @query maybe { p }",
        "% @query yes { p(X) }",
        "% @brave { p } assuming { X }",
    )
    assert all(d.span is not None for d in contract.diagnostics)
    assert [d.span.start.line for d in contract.diagnostics if d.span] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert len(contract.claims) == 1


def test_a_contract_needs_exactly_one_expect_and_unsat_admits_no_answer_set_claim() -> None:
    assert messages("% @count 1")[0].startswith("missing")
    assert "more than once" in messages("% @expect sat", "% @expect unsat")[0]
    clash = messages("% @expect unsat", "% @cautious { p }")
    assert "answer-set claim under" in clash[0]
    assert not messages("% @expect unsat", "% @count 0")
    assert not messages("% @expect unsat", "% @cautious { p } assuming { q }")


def test_a_claim_renders_as_the_line_that_reads_back_to_it() -> None:
    lines = [
        "@expect sat",
        "@count 3",
        "@answer-set { -p, q(1) }",
        "@cautious { p } assuming { not r, s }",
        '@brave { q("a,b") }',
        "@query unknown { p(1), -q }",
        "@query yes { p(X,b) } = { 1, 2 }",
        "@query no { p(X,Y) } = { (a,1), (b,2) }",
        "@query yes { p(f(X),b) } = { 1, 2 }",
        "@query no { p(f(g(X,1),a),(Y,-h(X))) } = { (1,2) }",
        "@query optimal yes { b }",
        "@query optimal no { p(X) } = { 1 }",
        "@expect unsat assuming { p }",
        "@count optimal 2",
        "@answer-set optimal { p, -q }",
        "@cautious optimal { p } assuming { r }",
        "@brave optimal { q }",
        "@cost { 3 -1 0 }",
        "@assign { x=1, y(a)=-2 }",
        "@assign optimal { x=1 }",
        "@answer-set { p } where { x=1 }",
        "@answer-set optimal { p, q } where { f(a,1)=0, x=3 } assuming { r }",
    ]
    contract = parse(*(f"% {line}" for line in lines))
    assert not contract.diagnostics
    assert [render(c) for c in contract.claims] == lines


def test_a_count_of_zero_contradicts_expecting_sat() -> None:
    contract = parse("% @expect sat", "% @count 0")
    assert [d.message for d in contract.diagnostics] == ["`@count 0` contradicts `@expect sat`"]
    assert not parse("% @expect unsat", "% @count 0").diagnostics


def only_diagnostic(*lines: str) -> Diagnostic:
    (found,) = parse("% @expect sat", *lines).diagnostics
    assert found.span is not None
    return found


def test_the_answer_set_tag_has_a_hyphen_and_the_old_spelling_is_not_a_tag() -> None:
    assert only("% @answer-set { p }").reading == Witness(frozenset({Literal("p")}))
    found = only_diagnostic("% @model { p }")
    assert found.message == "unknown tag `@model`"
    assert [c.message for c in found.children] == ["the tag is spelled `@answer-set`"]


def test_an_unknown_tag_names_a_close_one_as_help() -> None:
    found = only_diagnostic("% @expct sat")
    assert [c.message for c in found.children] == ["there is a tag with a similar name: `@expect`"]


def test_a_string_may_hold_escaped_quotes_commas_and_braces() -> None:
    claim = only(r'% @brave { q("a\"}b,c") }')
    assert claim.reading == Entails(Mode.BRAVE, frozenset({Literal("q", (String('a"}b,c'),))}))


def test_a_brace_group_continues_over_comment_lines_and_keeps_its_places() -> None:
    found = only_diagnostic("% @cautious { p,", "%   q(X) }")
    assert found.span is not None
    assert (found.span.start, found.span.end) == (P(2, 14), P(3, 10))


@pytest.mark.parametrize(
    ("line", "message", "start", "end"),
    [
        ("% @count x", "expected a non-negative integer, found `x`", P(2, 10), P(2, 11)),
        ("%   @count   x  ", "expected a non-negative integer, found `x`", P(2, 14), P(2, 15)),
        ("% @cautious p", "expected `{ literals }`, found `p`", P(2, 13), P(2, 14)),
        ("% @cautious { not p }", "expected ground literals, found `not p`", P(2, 14), P(2, 21)),
        ("% @cautious { }", "expected at least one literal, found `{ }`", P(2, 14), P(2, 15)),
        (
            "% @query maybe { p }",
            "expected `yes`, `no`, or `unknown`, found `maybe`",
            P(2, 10),
            P(2, 15),
        ),
        (
            "% @query yes { p(X) }",
            "query with variables states no bindings",
            P(2, 15),
            P(2, 21),
        ),
        (
            "% @query yes { p(X) } 1",
            "expected `ANSWER { query }` or `ANSWER { q(X) } = { bindings }`",
            P(2, 10),
            P(2, 24),
        ),
        (
            "% @query yes { p(X), q(Y) } = { 1 }",
            "expected one positive pattern before `=`, found `{ p(X), q(Y) }`",
            P(2, 15),
            P(2, 27),
        ),
        (
            "% @query yes { not p(X) } = { 1 }",
            "expected one positive pattern before `=`, found `{ not p(X) }`",
            P(2, 15),
            P(2, 25),
        ),
        (
            "% @query yes { p(1) } = { 1 }",
            "binding pattern has no variables",
            P(2, 15),
            P(2, 21),
        ),
        (
            "% @query yes { p(_, X) } = { 1 }",
            "anonymous variable in a binding pattern",
            P(2, 15),
            P(2, 24),
        ),
        (
            "% @query yes { p(_) } = { }",
            "anonymous variable in a binding pattern",
            P(2, 15),
            P(2, 21),
        ),
        (
            "% @cautious { p } assuming p",
            "expected `assuming { literals }`, found `assuming p`",
            P(2, 19),
            P(2, 29),
        ),
        (
            "% @cautious { p } assuming { q } extra",
            "expected `assuming { literals }`, found `assuming { q } extra`",
            P(2, 19),
            P(2, 39),
        ),
        ("% @cautious { p", "unclosed brace", P(2, 3), P(2, 16)),
        ("% @query yes { p. q }", "expected a list of literals, found `p. q`", P(2, 15), P(2, 21)),
        (
            "% @query yes { p(1..2) }",
            "`(1..2)` is not a pattern",
            P(2, 16),
            P(2, 23),
        ),
    ],
)
def test_a_bad_tag_is_one_diagnostic_at_the_text_that_is_wrong(
    line: str, message: str, start: Position, end: Position
) -> None:
    found = only_diagnostic(line)
    assert found.span is not None
    assert (found.message, found.span.start, found.span.end) == (message, start, end)


def test_a_missing_expect_is_reported_without_a_span() -> None:
    (found,) = parse("% @count 1").diagnostics
    assert found.span is None
    assert [d.message for d in parse("% @expect sat", "% @expect sat").diagnostics] == [
        "`@expect` given more than once"
    ]


def test_a_bad_literal_is_placed_in_the_comment_line_it_was_written_on() -> None:
    found = only_diagnostic("% @brave { p,", "%      q(1..2),", "%   r }")
    assert found.message == "`(1..2)` is not a pattern"
    assert found.label == "an interval stands for several terms"
    assert found.span is not None
    assert (found.span.start, found.span.end) == (P(3, 8), P(3, 15))


def test_optimal_is_a_range_a_claim_may_name_and_the_tag_is_sugar_for_it() -> None:
    p = frozenset({Literal("p")})
    assert only("% @optimal { p }").reading == Witness(p, Range.OPTIMAL)
    assert only("% @answer-set optimal { p }").reading == Witness(p, Range.OPTIMAL)
    assert only("% @cautious optimal { p }").reading == Entails(Mode.CAUTIOUS, p, Range.OPTIMAL)
    assert only("% @brave optimal { p }").reading == Entails(Mode.BRAVE, p, Range.OPTIMAL)
    assert only("% @count optimal 3").reading == Census(3, Range.OPTIMAL)
    assert only("% @cost { 2 -1 }").reading == Costs((2, -1))
    assert only("% @query optimal yes { p }").reading == Asks(
        Answer.YES, All((Literal("p"),)), Range.OPTIMAL
    )
    assert only("% @query optimal no { p(X) } = { 1 }").reading == Binds(
        Answer.NO, Pattern("p", (X,)), frozenset({(Number(1),)}), Range.OPTIMAL
    )


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("% @cost { }", "expected `{ c1 c2 ... }`, found `{ }`"),
        ("% @cost { 1 x }", "expected `{ c1 c2 ... }`, found `{ 1 x }`"),
        ("% @cost 3", "expected `{ c1 c2 ... }`, found `3`"),
        ("% @optimal optimal { p }", "expected `{ literals }`, found `optimal { p }`"),
        ("% @answer-set optimal", "expected `{ literals }`, found `{ }`"),
        ("% @count optimal", "expected a non-negative integer, found `{ }`"),
        ("% @count optimal { 1 }", "expected a non-negative integer, found `{ 1 }`"),
        (
            "% @query optimal",
            "expected `ANSWER { query }` or `ANSWER { q(X) } = { bindings }`",
        ),
        (
            "% @query yes optimal { p }",
            "expected `ANSWER { query }` or `ANSWER { q(X) } = { bindings }`",
        ),
    ],
)
def test_a_malformed_optimal_or_cost_claim_is_a_diagnostic(line: str, message: str) -> None:
    assert only_diagnostic(line).message == message


def test_no_optimal_answer_sets_follows_the_same_rule_as_no_answer_sets() -> None:
    assert not messages("% @expect unsat", "% @count optimal 0")
    assert "answer-set claim under" in messages("% @expect unsat", "% @cost { 1 }")[0]
    assert "contradicts `@expect sat`" in messages("% @expect sat", "% @count optimal 0")[0]


def test_more_optimal_answer_sets_than_answer_sets_is_a_contradiction() -> None:
    (message,) = messages("% @expect sat", "% @count 1", "% @count optimal 2")
    assert message == "`@count optimal 2` exceeds `@count 1`"
    assert not messages("% @expect sat", "% @count 2", "% @count optimal 2")
    assert not messages("% @expect sat", "% @count optimal 5")
    assert not messages("% @expect sat", "% @count 1", "% @count optimal 2 assuming { p }")


def test_an_expectation_is_sat_or_unsat() -> None:
    found = only_diagnostic("% @expect maybe")
    assert found.message == "expected `sat` or `unsat`, found `maybe`"
    assert found.span == Span("c.lp", P(2, 11), P(2, 16))


def test_a_malformed_expect_is_not_also_missing() -> None:
    assert messages("% @expect maybe") == ["expected `sat` or `unsat`, found `maybe`"]


X1, Y2 = Valuation(parse_term("x"), 1), Valuation(parse_term("y"), 2)


def test_assign_reads_the_integers_some_answer_set_gives_theory_variables() -> None:
    assert only("% @assign { x = 1, y=2 }").reading == Assigns(frozenset({X1, Y2}))
    assert only("% @assign optimal { x=1 }").reading == Assigns(frozenset({X1}), Range.OPTIMAL)


def test_a_witness_may_bind_the_assignment_of_the_same_answer_set_with_where() -> None:
    p = frozenset({Literal("p")})
    assert only("% @answer-set { p } where { x=1 }").reading == Witness(
        p, assignment=frozenset({X1})
    )
    assert only("% @optimal { p } where { x=1, y=2 }").reading == Witness(
        p, Range.OPTIMAL, frozenset({X1, Y2})
    )
    assert only("% @answer-set { p } where { x=1 } assuming { q }").scenario == frozenset(
        {Assumption(Literal("q"))}
    )


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("% @assign { }", "expected at least one `term = integer`, found `{ }`"),
        ("% @assign { x=1, x=2 }", "a term is assigned more than once"),
        ("% @assign { x }", "expected `term = integer`, found `x`"),
        ("% @assign x=1", "expected `{ term = integer, ... }`, found `x = 1`"),
        ("% @assign", "expected `{ term = integer, ... }`, found `{ }`"),
        (
            "% @assign { x=1 } { y=2 }",
            "expected `{ term = integer, ... }`, found `{ x=1 } { y=2 }`",
        ),
        (
            "% @assign optimal optimal { x=1 }",
            "expected `{ term = integer, ... }`, found `optimal { x=1 }`",
        ),
        ("% @answer-set { p } where { }", "expected at least one `term = integer`, found `{ }`"),
        (
            "% @answer-set { p } where x=1",
            "expected `where { term = integer, ... }`, found `where x = 1`",
        ),
        (
            "% @answer-set { p } where { x=1 } extra",
            "expected `where { term = integer, ... }`, found `where { x=1 } extra`",
        ),
        ("% @answer-set { } where { x=1 }", "expected at least one literal, found `{ }`"),
        ("% @answer-set { p } where { x=a }", "expected `term = integer`, found `x = a`"),
    ],
)
def test_a_malformed_assignment_is_a_diagnostic(line: str, message: str) -> None:
    assert only_diagnostic(line).message == message


def test_the_assignment_is_the_same_whether_a_term_is_repeated_with_the_same_integer() -> None:
    assert only("% @assign { x=1, x=1 }").reading == Assigns(frozenset({X1}))


def test_a_contract_declares_its_solver_and_defaults_to_clingo() -> None:
    assert parse("% @expect sat").solver is Solver.CLINGO
    declared = parse("% @expect sat", "% @elenctic solver clingcon")
    assert (declared.solver, declared.diagnostics) == (Solver.CLINGCON, ())
    assert len(declared.claims) == 1


@pytest.mark.parametrize(
    ("line", "message"),
    [
        ("% @elenctic solver cplex", "unknown solver `cplex`"),
        ("% @elenctic solver", "missing solver name"),
        ("% @elenctic mode fast", "unknown `@elenctic` directive `mode`"),
        ("% @elenctic", "unknown `@elenctic` directive"),
    ],
)
def test_a_misdeclared_solver_is_a_diagnostic_at_its_line(line: str, message: str) -> None:
    found = only_diagnostic(line)
    assert found.span is not None
    assert (found.message, found.span.start.line) == (message, 2)


def test_an_unknown_solver_name_is_the_primary_span() -> None:
    found = only_diagnostic("% @elenctic solver cplex")
    assert found.span is not None
    assert found.span.start.column == found.span.end.column - len("cplex")
    line = "% @elenctic solver cplex"
    assert line[found.span.start.column - 1 : found.span.end.column - 1] == "cplex"


def test_an_unknown_elenctic_directive_points_at_its_word() -> None:
    found = only_diagnostic("% @elenctic mode fast")
    assert found.span is not None
    line = "% @elenctic mode fast"
    assert line[found.span.start.column - 1 : found.span.end.column - 1] == "mode"


def test_only_one_solver_may_be_declared() -> None:
    contract = parse("% @expect sat", "% @elenctic solver clingo", "% @elenctic solver clingcon")
    (found,) = contract.diagnostics
    assert found.span is not None
    assert (found.message, found.span.start.line) == ("solver declared more than once", 3)
    assert contract.solver is Solver.CLINGO


def test_an_assumption_with_a_variable_is_refused_as_not_ground() -> None:
    found = messages("% @expect sat", "% @brave { p } assuming { q(X) }")
    assert len(found) == 1
    assert "ground" in found[0]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (("% @query yes { p.", "%   q }"), "expected a list of literals, found `p. q`"),
        (
            ("% @query yes { p(X),", "%   q(Y) } = { 1 }"),
            "expected one positive pattern before `=`, found `{ p(X), q(Y) }`",
        ),
        (
            ("% @query yes { p(X) } = { 1 +,", "%   2 }"),
            "expected a set of terms, found `1 +, 2`",
        ),
    ],
)
def test_found_text_written_over_lines_is_shown_on_one(
    lines: tuple[str, ...], message: str
) -> None:
    assert only_diagnostic(*lines).message == message
