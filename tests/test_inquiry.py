"""Why an atom holds or not in an answer set of a program, and what a query comes to over them."""

from pathlib import Path

from elenctic.determination import NoAssumptions, Range, These, Truncation
from elenctic.explanation import Explanation
from elenctic.inquiry import AskExit, WhyExit, ask, why
from elenctic.literals import Assumption, Literal
from elenctic.program import Fault, Locus, Program
from elenctic.query import All, Answer, Answered
from elenctic.report import Internal
from elenctic.search import Limits
from elenctic.verdicts import Ended

CHAIN = "edge(a,b). edge(b,c). reach(a). reach(Y) :- reach(X), edge(X,Y).\n"


def test_why_explains_an_atom_in_the_first_answer_set() -> None:
    explained = why(Program(CHAIN, "chain.lp"), Literal.parse("reach(c)"))
    assert isinstance(explained, Explanation)
    assert explained.counterexample.index == 1
    assert explained.roots
    assert WhyExit.of(explained) is WhyExit.EXPLAINED


def test_why_explains_the_answer_set_asked_for_by_its_index() -> None:
    explained = why(Program("{ a; b }.", "t.lp"), Literal("a"), index=3)
    assert isinstance(explained, Explanation)
    assert (explained.counterexample.index, explained.counterexample.read) == (3, 4)


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
    explained = why(Program.read(late), Literal("late"))
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
    ended = ask(Program("{ a }.", "t.lp"), All((Literal("a"),)), limits=Limits(max_answer_sets=1))
    assert AskExit.of(ended) is AskExit.ENDED
    assert AskExit.of(Internal("ValueError", "x")) is AskExit.INTERNAL_ERROR
