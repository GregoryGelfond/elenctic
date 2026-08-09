"""`@cautious`/`@brave` claim membership of ⋂ AS(P) / ⋃ AS(P), and elenctic reads the shown
projection of the answer sets. Where the projection does not carry a claimed literal's signature,
the literal is absent from every answer set elenctic can see, so the claim is FAILed whatever the
program computes — including when it is true.

These run end to end through `discover` (where the precondition fires) and `run_case` (which
produces the verdict), because the defect is a corpus reporting a confident FAIL about a claim that
is true, and nothing short of running one shows that.

The polarity is the opposite of `test_query_gate`'s and that is the point: those fixtures are false
claims wrongly certified, these are **true claims wrongly failed**. So the control differs too —
each body is re-run with its `#show` lines stripped, and the claim must **PASS** there.
"""

import re
from pathlib import Path

import pytest

from elenctic.discovery import DiscoveryError, discover
from elenctic.harness import case_verdict, run_case
from elenctic.result import Verdict

_SHOW = re.compile(r"^#show\b.*$", re.MULTILINE)


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _answer(tmp_path: Path, name: str, body: str) -> tuple[Verdict, tuple[str, ...]]:
    """Run one case, and return its verdict with the message of every check it reported."""
    (case,) = discover(_write(tmp_path, name, body))
    reports = run_case(case)
    return case_verdict(reports), tuple(report.message for report in reports)


# --- the wrong answers: a TRUE membership claim reported FAIL, one per field ---

# `p(x)` is a fact, so it is in every answer set and in every optimal one: each claim below is
# true. Each program declares something else observable, so `p(x)` reaches no projection and the
# claim was failed. The optimal pair carry a `#minimize` because the optimal-base tags require an
# optimizing encoding, and a choice rule so that the optimum is not the only answer set.
_OPTIMIZING = "p(x). q(x). { r }.\n#minimize{ 1,r : r }.\n"
_PLAIN = "p(x). q(x).\n"

_UNDECLARED = [
    ("cautious", f"% @expect sat\n% @cautious {{ p(x) }}\n{_PLAIN}#show q/1.\n"),
    ("brave", f"% @expect sat\n% @brave {{ p(x) }}\n{_PLAIN}#show q/1.\n"),
    (
        "cautious-optimal",
        f"% @expect sat\n% @cautious optimal {{ p(x) }}\n{_OPTIMIZING}#show q/1.\n",
    ),
    ("brave-optimal", f"% @expect sat\n% @brave optimal {{ p(x) }}\n{_OPTIMIZING}#show q/1.\n"),
]

# The other half of the rule, and the shape kr-domains is actually written in: the signature is
# not declared but a `#show <term> : <body>.` directive displays it. `cost(b,2)` is a fact, so it
# is a cautious consequence; the directive emits a cost only for a SELECTED item, and `b` is not
# selected, so the atom never reaches the output and the true claim was failed. The remedy differs
# from the one above, which is the whole reason the two are told apart.
_DISPLAYED = [
    (
        "displayed-cautious",
        "% @expect sat\n% @cautious { cost(b,2) }\nsel(a). cost(a,1). cost(b,2).\n"
        "#show sel/1.\n#show cost(X,C) : sel(X), cost(X,C).\n",
    ),
    (
        "displayed-brave",
        "% @expect sat\n% @brave { cost(b,2) }\nsel(a). cost(a,1). cost(b,2).\n"
        "#show sel/1.\n#show cost(X,C) : sel(X), cost(X,C).\n",
    ),
]

_REFUSED = _UNDECLARED + _DISPLAYED


@pytest.mark.parametrize(("name", "body"), _REFUSED, ids=[r[0] for r in _REFUSED])
def test_a_claim_the_program_cannot_answer_is_refused_not_failed(
    tmp_path: Path, name: str, body: str
) -> None:
    with pytest.raises(DiscoveryError, match=r"reads .*, which the program"):
        discover(_write(tmp_path, f"{name}.lp", body))


@pytest.mark.parametrize(("name", "body"), _REFUSED, ids=[r[0] for r in _REFUSED])
def test_each_refused_claim_really_was_true(tmp_path: Path, name: str, body: str) -> None:
    """Every contract above is refused. This is what establishes that each one *deserved* to be.

    A test asserting an input is rejected proves nothing about the input: it passes just as well
    over a claim that was false all along, and would then be defending an over-refusal while
    reading as a wrong-answer guard. So each body is re-run with its `#show` lines stripped — a
    program that shows every atom, whose projection is the identity — and the claim must **PASS**
    there. That is the measurement that the claim is true and the FAIL was a wrong answer, rather
    than a comment saying so.
    """
    verdict, messages = _answer(tmp_path, f"{name}-control.lp", _SHOW.sub("", body))
    assert verdict is Verdict.PASS, (
        f"{name}: the claim fails against a program that hides nothing, so this fixture is not a "
        f"true claim and the refusal above is not a wrong-answer guard. {messages}"
    )


@pytest.mark.parametrize(("name", "body"), _UNDECLARED, ids=[r[0] for r in _UNDECLARED])
def test_the_undeclared_refusal_says_what_to_declare(tmp_path: Path, name: str, body: str) -> None:
    with pytest.raises(DiscoveryError, match=r"does not declare observable") as raised:
        discover(_write(tmp_path, f"{name}.lp", body))
    assert "#show p/1." in str(raised.value), str(raised.value)


@pytest.mark.parametrize(("name", "body"), _DISPLAYED, ids=[r[0] for r in _DISPLAYED])
def test_the_displayed_refusal_does_not_say_to_declare_the_predicate(
    tmp_path: Path, name: str, body: str
) -> None:
    """The two refusals differ in remedy, and this is the half where the other one is destructive.

    Declaring `cost/2` widens the output from the selected costs to the whole input table, which
    silently breaks every contract stating a whole observable — measured on a real corpus, where
    it is eight `@optimal` lines that are not otherwise in this gate's blast radius.
    """
    with pytest.raises(DiscoveryError, match=r"displays with") as raised:
        discover(_write(tmp_path, f"{name}.lp", body))
    message = str(raised.value)
    assert "#show cost/2." not in message, message
    assert "a name of its own" in message, message


# --- the allowing direction: a rule asserted in one direction cannot detect its own weakening ---


_ALLOWED = [
    # Declared, plainly. The claim is true and must be answered, not refused.
    ("declared", f"% @expect sat\n% @cautious {{ p(x) }}\n{_PLAIN}#show p/1.\n"),
    # No declaration form at all, so every atom reaches the output — and a display directive on
    # top of that adds nothing, because `_projection_of` keeps only symbols the model contains.
    # Widen the rule to refuse on `displayed` alone and this case is refused.
    (
        "unrestricted-with-a-display",
        "% @expect sat\n% @cautious { p(x) }\np(x). q(x).\n#show hello : q(x).\n",
    ),
    # Declared AND displayed. The declaration projects the signature exactly; the directive can
    # only re-emit atoms already there. Widen the rule to ask `displayed` of a declared signature
    # and this case is refused.
    (
        "declared-and-displayed",
        "% @expect sat\n% @cautious { p(x) }\np(x). q(x).\n#show p/1.\n#show p(y) : q(x).\n",
    ),
]


@pytest.mark.parametrize(("name", "body"), _ALLOWED, ids=[r[0] for r in _ALLOWED])
def test_a_claim_the_program_can_answer_is_answered(tmp_path: Path, name: str, body: str) -> None:
    verdict, messages = _answer(tmp_path, f"{name}.lp", body)
    assert verdict is Verdict.PASS, messages


def test_the_refusal_sites_the_contract_line_it_is_about(tmp_path: Path) -> None:
    body = f"% @expect sat\n%\n%\n% @cautious {{ p(x) }}\n{_PLAIN}#show q/1.\n"
    with pytest.raises(DiscoveryError) as raised:
        discover(_write(tmp_path, "sited.lp", body))
    assert raised.value.line == 4, (raised.value.line, str(raised.value))
