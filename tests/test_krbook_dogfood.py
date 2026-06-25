"""``@query`` dogfood — the three-valued epistemic query on Gelfond–Kahl's own programs.

elenctic exercises its ``@query`` machinery (Def 2.2.2, errata-corrected) end-to-end against the
canonical KRBOOK examples (vendored verbatim under ``tests/krbook/`` with a ``#show`` + ``@query``
contract appended; the kr-domains corpus is untouched). These default-reasoning programs each have a
single answer set, so the cautious consequences ⋂ *are* that answer set, and the contracts encode
the textbook's own yes/no/**unknown** answers, including the three-valued cases (cowardly's CS
student, uncaring's unknown parent) that classical logic cannot express.

The dogfood runs the full pipeline (discover → parse ``@query`` → ``runs_for`` → solve → check →
verdict), so a regression anywhere in the ``@query`` path surfaces here as a failing contract.
"""

from pathlib import Path

import pytest

from elenctic.checks import query_matches
from elenctic.discovery import Case, discover
from elenctic.harness import case_verdict, render, run_case
from elenctic.query import parse_query
from elenctic.result import Verdict
from elenctic.run import Mode
from elenctic.solvers import run_clingo

_KRBOOK = Path(__file__).parent / "krbook"
_PROGRAMS = ("orphans", "tweety", "cowardly", "uncaring")


def _cases() -> dict[str, Case]:
    """The discovered KRBOOK cases, keyed by program name (each a self-contained case file)."""
    return {case.path.stem: case for case in discover(_KRBOOK / "encodings")}


def test_all_four_krbook_programs_are_discovered() -> None:
    assert set(_cases()) == set(_PROGRAMS)


@pytest.mark.parametrize("program", _PROGRAMS)
def test_krbook_query_contract_holds(program: str) -> None:
    # The textbook's yes/no/unknown answers hold under the program's actual answer set.
    case = _cases()[program]
    reports = run_case(case)
    assert case_verdict(reports) is Verdict.PASS, render(case, reports)


def test_every_query_answer_is_exercised_across_the_corpus() -> None:
    # The dogfood spans all three answers (yes/no/unknown), end-to-end across the four programs.
    messages = " ".join(
        report.message
        for program in _PROGRAMS
        for report in run_case(_cases()[program])
        if report.label == "@query"
    )
    assert "computed yes" in messages
    assert "computed no" in messages
    assert "computed unknown" in messages


def test_unknown_is_genuinely_distinguished_from_yes_and_no() -> None:
    # cowardly's bob (CS) is *unknown*, the value the relation vocabulary cannot express. The
    # correct `unknown` PASSes, while asserting `yes` or `no` FAILs — the @query check discriminates
    # all three, not presence alone.
    program = (_KRBOOK / "encodings" / "cowardly" / "cowardly.lp").read_text()
    determination = run_clingo(Mode.CAUTIOUS_ALL, program)  # the singleton-query run reads ⋂
    correct = query_matches(parse_query("unknown", "{ afraid(bob,math) }"))
    assert correct(determination).verdict is Verdict.PASS
    for wrong_answer in ("yes", "no"):
        report = query_matches(parse_query(wrong_answer, "{ afraid(bob,math) }"))(determination)
        assert report.verdict is Verdict.FAIL
        assert "computed unknown" in report.message  # expected yes/no, computed unknown
