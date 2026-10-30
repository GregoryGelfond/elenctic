from clingo import Number, String, parse_term

from aspnext.contract import (
    Asks,
    Binds,
    Census,
    Claim,
    Contract,
    Entails,
    Satisfiable,
    Witness,
    is_case,
    parse_contract,
    render,
)
from aspnext.determination import Mode
from aspnext.literals import Assumption, Literal, Pattern, Variable
from aspnext.query import All, Answer
from aspnext.spans import Position, Span

X = Variable("X")


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
        "% @model { p, q }",
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
        "% @optimal { p }",
        "% @count two",
        "% @cautious { }",
        "% @cautious { X }",
        "% @query maybe { p }",
        "% @query yes { p(X) }",
        "% @brave { p } assuming { X }",
    )
    assert [d.span.start.line for d in contract.diagnostics] == [2, 3, 4, 5, 6, 7, 8, 9]
    assert len(contract.claims) == 1


def test_a_contract_needs_exactly_one_expect_and_unsat_admits_no_model_claim() -> None:
    assert messages("% @count 1")[0].startswith("missing")
    assert "more than one" in messages("% @expect sat", "% @expect unsat")[0]
    clash = messages("% @expect unsat", "% @cautious { p }")
    assert "no model" in clash[0]
    assert not messages("% @expect unsat", "% @count 0")
    assert not messages("% @expect unsat", "% @cautious { p } assuming { q }")


def test_a_claim_renders_as_the_line_that_reads_back_to_it() -> None:
    lines = [
        "@expect sat",
        "@count 3",
        "@model { -p, q(1) }",
        "@cautious { p } assuming { not r, s }",
        '@brave { q("a,b") }',
        "@query unknown { p(1), -q }",
        "@query yes { p(X,b) } = { 1, 2 }",
        "@query no { p(X,Y) } = { (a,1), (b,2) }",
        "@expect unsat assuming { p }",
    ]
    contract = parse(*(f"% {line}" for line in lines))
    assert not contract.diagnostics
    assert [render(c) for c in contract.claims] == lines
