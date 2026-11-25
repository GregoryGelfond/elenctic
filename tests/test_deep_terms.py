"""A term nested deeper than Python's stack is read, answered and explained as a shallow one is."""

import pytest
from clingo import parse_term
from clingo.ast import AST, parse_string

from elenctic import instances
from elenctic.check import check
from elenctic.clauses import global_names_in, names_in
from elenctic.inquiry import ask, why
from elenctic.literals import Literal
from elenctic.patterns import Pattern
from elenctic.program import Program
from elenctic.query import All, Answer, Answered, Answers, Warrant
from elenctic.session import Session, evidenced, session
from elenctic.terms import Variable
from elenctic.verdicts import Report

DEPTH = 5000


def _nested(depth: int) -> str:
    return "f(" * depth + "a" + ")" * depth


DEEP = f"p({_nested(DEPTH)}).\nq :- p(X).\n"


def _statement(text: str) -> AST:
    found: list[AST] = []
    parse_string(text, found.append)
    return found[-1]


def test_the_variables_of_a_deep_rule_are_named_in_the_order_written() -> None:
    rule = _statement(f"h(Y, X) :- p({'f(' * DEPTH}X{')' * DEPTH}), #count {{ Z: q(Z, Y) }} > 0.")
    assert names_in(rule, "fresh") == ["Y", "X", "Z"]
    assert global_names_in(rule, "fresh") == ["Y", "X"]


def test_a_deep_symbol_orders_the_instances_it_binds() -> None:
    made = session(Program(f"p({_nested(DEPTH)}). p(b).\nq(X) :- p(X).\n", "t.lp"))
    assert isinstance(made, Session)


def test_a_query_of_a_deep_program_is_answered_and_warranted() -> None:
    program = Program(DEEP, "t.lp")
    answered = ask(program, All((Literal("q"),)))
    assert isinstance(answered, Answered)
    assert answered.answer is Answer.YES
    assert isinstance(why(program, All((Literal("q"),))), Warrant)
    bound = ask(program, All((Pattern("p", (Variable("X"),)),)))
    assert isinstance(bound, Answered)
    assert isinstance(bound.answer, Answers)
    assert [each.values for each in bound.answer.bound] == [(parse_term(_nested(DEPTH)),)]


def test_a_failed_claim_of_a_deep_program_is_explained() -> None:
    program = Program(f"% @expect sat\n% @cautious {{ zz }}\n{DEEP}", "t.lp")
    report = check(program)
    assert isinstance(report, Report)
    assert isinstance(evidenced(report, program), Report)


@pytest.mark.parametrize(
    "term", ["p", "-p(1)", 'f(a, "x\\n", -3, (1, 2), -g(#inf), #sup)', "(1,)", "()", "f(())"]
)
def test_a_symbol_is_spelled_for_ordering_as_its_repr_spells_it(term: str) -> None:
    symbol = parse_term(term)
    assert instances.spelled(symbol) == repr(symbol)
