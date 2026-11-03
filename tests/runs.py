"""Runs of known programs, for the tests of the views."""

from elenctic.check import check
from elenctic.program import Fault, Program
from elenctic.report import Entry
from elenctic.search import UNLIMITED, Limits
from elenctic.verdicts import Report

PASSING = "p.\n% @expect sat\n% @cautious { p }\n"
FAILING = "p.\n% @expect sat\n% @cautious { q }\n"
UNDECIDED_COUNT = "{ p(1..2) }.\n#show p/1.\n% @expect sat\n% @count 4\n"
FAULTY = "p.\n% @count x\n"
PROGRAM_WITH_ESCAPE_CODES = 'p("\x1b[2J\x1b[31mRED\r").\n% @expect sat\n% @cautious { p("x") }\n'


def entry(text: str, source: str, limits: Limits = UNLIMITED) -> Entry:
    result = check(Program(text, source), limits=limits)
    assert isinstance(result, Report | Fault)
    return Entry(source, result)
