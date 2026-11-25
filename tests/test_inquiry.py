"""Why an atom holds or not in an answer set of a program, and what a query comes to over them."""

from collections.abc import Callable
from pathlib import Path

import pytest

from elenctic.determination import NoAssumptions, Range, These, Truncation
from elenctic.explanation import Explanation
from elenctic.inquiry import AskExit, WhyExit, ask, why
from elenctic.literals import Assumption, Function, Literal, Number, Symbol
from elenctic.patterns import Pattern
from elenctic.program import Fault, Locus, Program
from elenctic.query import All, Answer, Answered, AnswerMode, Not, Unreached, Warrant
from elenctic.report import Internal
from elenctic.search import Limits
from elenctic.terms import Variable
from elenctic.verdicts import Ended

CHAIN = "edge(a,b). edge(b,c). reach(a). reach(Y) :- reach(X), edge(X,Y).\n"


def test_why_explains_an_atom_in_the_first_answer_set() -> None:
    explained = why(Program(CHAIN, "chain.lp"), Literal.parse("reach(c)"), index=1)
    assert isinstance(explained, Explanation)
    assert explained.counterexample.index == 1
    assert explained.roots
    assert WhyExit.of(explained) is WhyExit.EXPLAINED


def test_why_explains_the_answer_set_asked_for_by_its_index() -> None:
    explained = why(Program("{ a; b }.", "t.lp"), Literal("a"), index=3)
    assert isinstance(explained, Explanation)
    assert (explained.counterexample.index, explained.counterexample.read) == (3, None)


def test_why_counts_the_optima_under_optimal() -> None:
    program = Program("1 { a; b; c } 1. #minimize { 1 : a; 1 : b; 2 : c }.", "t.lp")
    explained = why(program, Literal("c"), index=2, over=Range.OPTIMAL)
    assert isinstance(explained, Explanation)
    assert (explained.counterexample.index, explained.counterexample.read) == (2, 2)
    assert Literal("c") not in explained.counterexample.answer_set.atoms


def test_why_past_the_last_answer_set_is_a_fault_naming_how_many_there_are() -> None:
    refused = why(Program("{ a }.", "t.lp"), Literal("a"), index=3)
    assert isinstance(refused, Fault)
    assert refused.locus is Locus.REQUEST
    assert refused.diagnostics[0].message == "there is no answer set 3: the search read 2"
    assert WhyExit.of(refused) is WhyExit.FAULT


def test_a_fault_in_a_parameter_of_why_or_ask_is_placed_at_the_parameter() -> None:
    program = Program("{ p(1) }.", "t.lp")
    past = why(program, Literal("p", (Number(1),)), index=3)
    unbound = why(program, Pattern("p", (Variable("X"),)), values=(Number(2),))
    optimal = ask(program, All((Literal("p", (Number(1),)),)), over=Range.OPTIMAL)
    found = [
        each.diagnostics[0].span.source
        if isinstance(each, Fault) and each.diagnostics[0].span
        else None
        for each in (past, unbound, optimal)
    ]
    assert found == ["index", "values", "over"]
    assert isinstance(past, Fault)
    assert [child.message for child in past.diagnostics[0].children] == [
        "`index` counts from 1 to 2"
    ]


def test_why_without_answer_sets_gives_the_refutation() -> None:
    assert why(Program("a. :- a.", "t.lp"), Literal("a")) == NoAssumptions()
    clash = frozenset({Assumption(Literal("a")), Assumption(Literal("a"), holds=False)})
    refuted = why(Program("{ a }.", "t.lp"), Literal("a"), scenario=clash)
    assert isinstance(refuted, These)
    assert WhyExit.of(refuted) is WhyExit.FAULT


def test_why_on_a_search_that_stops_short_has_ended() -> None:
    ended = why(
        Program("{ a; b }.", "t.lp"), Literal("a"), index=3, limits=Limits(max_answer_sets=1)
    )
    assert ended == Ended(Truncation.MAX_ANSWER_SETS)
    assert WhyExit.of(ended) is WhyExit.ENDED


def test_why_on_a_program_that_does_not_ground_is_a_fault() -> None:
    refused = why(Program("p(X) :- q.", "t.lp"), Literal("p"))
    assert isinstance(refused, Fault)
    assert WhyExit.of(Internal("ValueError", "x")) is WhyExit.INTERNAL_ERROR


def test_why_refuses_an_include_outside_the_root(tmp_path: Path) -> None:
    (tmp_path / "in").mkdir()
    (tmp_path / "out.lp").write_text("a.\n")
    path = tmp_path / "in" / "p.lp"
    path.write_text('#include "../out.lp".\n')
    refused = why(Program.read(path), Literal("a"))
    assert isinstance(refused, Fault)


def test_why_takes_the_solver_a_contract_names() -> None:
    late = Path(__file__).parent.parent / "docs" / "examples" / "late.lp"
    explained = why(Program.read(late), Literal("late"), index=1)
    assert isinstance(explained, Explanation)
    assert explained.counterexample.answer_set.assignment


def test_ask_answers_a_query_over_every_answer_set() -> None:
    answered = ask(Program("{ a; b }.", "t.lp"), All((Literal("a"),)))
    assert isinstance(answered, Answered)
    assert answered.answer is Answer.UNKNOWN
    assert AskExit.of(answered) is AskExit.ANSWERED


def test_ask_answers_no_whatever_the_answer_is() -> None:
    answered = ask(Program("-b.", "t.lp"), All((Literal("b"),)))
    assert isinstance(answered, Answered)
    assert (answered.answer, AskExit.of(answered)) == (Answer.NO, AskExit.ANSWERED)


def test_ask_without_answer_sets_and_on_a_cut_search_does_not_answer() -> None:
    refuted = ask(Program("a. :- a.", "t.lp"), All((Literal("a"),)))
    assert refuted == NoAssumptions()
    assert AskExit.of(refuted) is AskExit.FAULT
    both = All((Literal("a"), Literal("b")))
    ended = ask(Program("{ a; b }.", "t.lp"), both, limits=Limits(max_answer_sets=1))
    assert AskExit.of(ended) is AskExit.ENDED
    assert AskExit.of(Internal("ValueError", "x")) is AskExit.INTERNAL_ERROR


def test_a_brave_answer_found_before_the_search_was_cut_exits_as_cut() -> None:
    pattern = Pattern("p", (Variable("X"),))
    program = Program("p(1). { p(2) }.", "t.lp")
    found = ask(program, pattern, mode=AnswerMode.BRAVE, limits=Limits(max_answer_sets=1))
    assert isinstance(found, Answered)
    assert (found.cut, AskExit.of(found)) == (Truncation.MAX_ANSWER_SETS, AskExit.ENDED)


def test_why_without_an_answer_set_warrants_the_answer_of_a_query() -> None:
    found = why(Program("{ a }. b.", "t.lp"), All((Literal("b"),)))
    assert isinstance(found, Warrant)
    assert (found.answer, [each.answer for each in found.witnesses]) == (Answer.YES, [Answer.YES])
    assert (found.refutation, found.mode, found.over, found.read) == (
        NoAssumptions(),
        AnswerMode.DEFAULT,
        Range.ALL,
        None,
    )
    assert WhyExit.of(found) is WhyExit.EXPLAINED


def test_why_warrants_the_answer_its_mode_gives() -> None:
    found = why(Program("{ a }. -b.", "t.lp"), All((Literal("b"),)), mode=AnswerMode.BRAVE)
    assert isinstance(found, Warrant)
    assert (found.answer, found.witnesses, found.refutation, found.mode) == (
        Answer.NONE_HOLDS,
        (),
        NoAssumptions(),
        AnswerMode.BRAVE,
    )


def test_why_warrants_one_binding_of_a_query_with_variables() -> None:
    reach = All((Pattern("r", (Variable("X"),)), Not(Pattern("c", (Variable("X"),)))))
    program = Program("r(a). r(b). { c(b) }. c(c).", "t.lp")
    found = why(program, reach, values=(Function("a"),))
    assert isinstance(found, Warrant)
    assert found.query == All((Literal("r", (Function("a"),)), Not(Literal("c", (Function("a"),)))))
    assert found.answer is Answer.YES


@pytest.mark.parametrize(
    ("query", "values", "message"),
    [
        (
            Pattern("p", (Variable("X"),)),
            (),
            "a query with variables is warranted one binding at a time",
        ),
        (Pattern("p", (Variable("X"),)), (Number(2),), "the query has no binding to X = 2"),
        (
            All((Literal("p", (Number(1),)),)),
            (Number(1),),
            "a query without variables has no binding to warrant",
        ),
    ],
)
def test_why_refuses_a_binding_the_query_does_not_have(
    query: Pattern | All, values: tuple[Symbol, ...], message: str
) -> None:
    refused = why(Program("p(1).", "t.lp"), query, values=values)
    assert isinstance(refused, Fault)
    assert (refused.locus, refused.diagnostics[0].message) == (Locus.REQUEST, message)
    assert WhyExit.of(refused) is WhyExit.FAULT


def test_why_of_a_binding_a_cut_brave_search_did_not_read_says_it_was_cut() -> None:
    program, p = Program("{ p(1..3) }.", "t.lp"), Pattern("p", (Variable("X"),))
    brave, cut = AnswerMode.BRAVE, Limits(max_answer_sets=2)
    found = why(program, p, values=(Number(2),), mode=brave, limits=cut)
    assert isinstance(found, Warrant)
    assert found.answer is Answer.YES
    unread = why(program, p, values=(Number(3),), mode=brave, limits=cut)
    assert unread == Ended(Truncation.MAX_ANSWER_SETS)
    assert WhyExit.of(unread) is WhyExit.ENDED


def test_why_explains_an_answer_set_only_of_one_ground_literal() -> None:
    untyped: Callable[..., object] = why
    with pytest.raises(TypeError, match="one ground literal"):
        untyped(Program("a.", "t.lp"), All((Literal("a"),)), index=1)


def test_why_warrants_over_the_optima_by_the_search_that_read_them_all() -> None:
    program = Program("1 { a; b; c } 1. #minimize { 1 : a; 1 : b; 2 : c }.", "t.lp")
    found = why(program, All((Not(Literal("c")),)), over=Range.OPTIMAL)
    assert isinstance(found, Warrant)
    assert (found.answer, found.refutation, found.over, found.read) == (
        Answer.YES,
        None,
        Range.OPTIMAL,
        2,
    )


def test_why_names_the_witness_a_cut_search_did_not_reach() -> None:
    program = Program("{ a; -a } = 1.", "t.lp")
    found = why(program, All((Literal("a"),)), limits=Limits(max_answer_sets=1))
    assert isinstance(found, Warrant)
    assert found.answer is Answer.UNKNOWN
    assert len(found.witnesses) == 1
    assert [type(each) for each in found.unreached] == [Unreached]
    assert found.unreached[0].answer is not found.witnesses[0].answer


def test_why_of_a_query_without_answer_sets_or_cut_short_gives_no_warrant() -> None:
    assert why(Program("a. :- a.", "t.lp"), All((Literal("a"),))) == NoAssumptions()
    both = All((Literal("a"), Literal("b")))
    ended = why(Program("{ a; b }.", "t.lp"), both, limits=Limits(max_answer_sets=1))
    assert ended == Ended(Truncation.MAX_ANSWER_SETS)
