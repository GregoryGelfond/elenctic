"""A @query is answered off the shown projection of the answer sets, never off the answer sets, so
the projection has to preserve everything the query reads.

These are end to end through `discover` (where the precondition fires) and `run_case` (which
produces the answer), because the defect this guards against is a corpus that reports `1/1 passed`
about a claim that is false — and nothing short of running one shows that.
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


# --- the routes that certified a false claim. Each was measured reporting `1/1 passed`, exit 0. ---


@pytest.mark.parametrize(
    ("name", "body"),
    [
        # A ground singleton whose POSITIVE literal is unshown. `p(x)` is a fact, so the true answer
        # is `yes`; unshown it can never enter ⋂, so the computed answer was `unknown` — the very
        # answer the contract claimed. The gate that existed covered only the contrary.
        (
            "positive-unshown",
            "% @expect sat\n% @query unknown { p(x) }\np(x).\n#show -p/1.\n",
        ),
        # The same, one form over: a conjunct is unshown while BOTH contraries are shown, so the
        # contrary gate is satisfied and nothing refused it. The true answer is `yes`.
        (
            "conjunct-unshown",
            "% @expect sat\n% @query unknown { p(x), q(x) }\np(x). q(x).\n"
            "#show -p/1.\n#show -q/1.\n#show q/1.\n",
        ),
        # A binding `no` stating the empty set with `-q` unshown. With the contrary unobservable the
        # computed no-set is FORCED empty, so the check cannot fail — which is what the carve-out
        # called "vacuously satisfiable". The true no-set is { (b) }.
        (
            "empty-no-set",
            "% @expect sat\n% @query no { q(X) } = { }\nq(a). -q(b).\n#show q/1.\n",
        ),
        # A binding `yes` stating the empty set with `q` unshown — the route no patch to the two
        # above would have closed, because the rule they shared returned nothing at all for a `yes`
        # binding. The true yes-set is { (a) }.
        (
            "empty-yes-set",
            "% @expect sat\n% @query yes { q(X) } = { }\nq(a). -q(b).\n#show -q/1.\n",
        ),
        # A program that shows nothing, stating the empty set. Nothing is observable, so both the
        # yes-set and the no-set are forced empty and neither claim can fail.
        (
            "shows-nothing-yes",
            "% @expect sat\n% @query yes { q(X) } = { }\nq(a). -q(b).\n#show.\n",
        ),
        (
            "shows-nothing-no",
            "% @expect sat\n% @query no { q(X) } = { }\nq(a). -q(b).\n#show.\n",
        ),
    ],
)
def test_a_query_the_program_cannot_answer_is_refused_not_certified(
    tmp_path: Path, name: str, body: str
) -> None:
    with pytest.raises(DiscoveryError, match=r"this @query reads"):
        discover(_write(tmp_path, f"{name}.lp", body))


def test_a_true_claim_is_no_longer_failed_for_an_unshown_contrary(tmp_path: Path) -> None:
    # The other half, and the reason the rule is about the answer rather than about the verdict: the
    # author who wrote the TRUE claim was told they were wrong. `p(x)` is a fact and the true answer
    # is `yes`, but with `-p` unshown the computed answer was `unknown`, so this FAILed while the
    # false `unknown` beside it passed. Now neither is answered: the program is asked to say.
    body = "% @expect sat\n% @query yes { p(x) }\np(x).\n#show p/1.\n"
    with pytest.raises(DiscoveryError, match=r"reads -p/1"):
        discover(_write(tmp_path, "true-claim.lp", body))


# --- the refusals that were spurious, and the false sentence that came with them ---


def test_a_program_with_no_show_answers_its_queries(tmp_path: Path) -> None:
    # Refused before, with a diagnostic reading "absent from the shown vocabulary {}" — false, since
    # a program with no #show shows every atom. `-fly(tweety)` is a fact, so the answer is `no`.
    verdict, messages = _answer(
        tmp_path,
        "no-show.lp",
        "% @expect sat\n% @query no { fly(tweety) }\nfly(sam). -fly(tweety).\n",
    )
    assert verdict is Verdict.PASS
    assert any("computed no" in message for message in messages), messages


def test_a_program_whose_only_show_is_a_term_directive_answers_its_queries(
    tmp_path: Path,
) -> None:
    # A `#show <term> : <body>.` directive does not restrict the output, so this program shows every
    # atom too — but it was read as declaring `label/1` and nothing else, which refused a query over
    # a literal that is in fact readable.
    verdict, messages = _answer(
        tmp_path,
        "term-only.lp",
        "% @expect sat\n% @query no { fly(tweety) }\n"
        "fly(sam). -fly(tweety). label(sam).\n#show label(X) : fly(X).\n",
    )
    assert verdict is Verdict.PASS
    assert any("computed no" in message for message in messages), messages


def test_a_conditionally_displayed_predicate_is_refused_rather_than_guessed(
    tmp_path: Path,
) -> None:
    # And where the program IS restricted, a term directive does not make its predicate readable:
    # `p(b)` is an atom of every answer set but is displayed only where `q` holds, so the true `yes`
    # was computed as `unknown` and reported as a FAIL against a correct contract.
    body = (
        "% @expect sat\n% @query yes { p(b) }\np(a). p(b). q(a).\n#show q/1.\n#show p(X) : q(X).\n"
    )
    with pytest.raises(DiscoveryError, match=r"appears in a `#show <term> : <body>\.` directive"):
        discover(_write(tmp_path, "conditional.lp", body))


# --- the guarantee itself, as a differential ---

_ADMITTED = [
    # (name, program, contract) — each shows exactly what its query reads.
    (
        "singleton-yes",
        "p(x). -q(x).\n#show p/1.\n#show -p/1.\n",
        "% @query yes { p(x) }\n",
    ),
    (
        "singleton-no",
        "p(x). -q(x).\n#show q/1.\n#show -q/1.\n",
        "% @query no { q(x) }\n",
    ),
    (
        "singleton-unknown",
        "{ r(x) }.\n#show r/1.\n#show -r/1.\n",
        "% @query unknown { r(x) }\n",
    ),
    (
        "conjunctive-yes",
        "p(x). q(x).\n#show p/1.\n#show -p/1.\n#show q/1.\n#show -q/1.\n",
        "% @query yes { p(x), q(x) }\n",
    ),
    (
        "conjunctive-no",
        "-p(x). -q(x).\n#show p/1.\n#show -p/1.\n#show q/1.\n#show -q/1.\n",
        "% @query no { p(x), q(x) }\n",
    ),
    (
        "binding-yes",
        "q(a). q(b). -q(c).\n#show q/1.\n",
        "% @query yes { q(X) } = { a, b }\n",
    ),
    (
        "binding-no",
        "q(a). -q(c).\n#show -q/1.\n",
        "% @query no { q(X) } = { c }\n",
    ),
    (
        "binding-unknown",
        "q(a). -q(c). { q(d) }.\n#show q/1.\n#show -q/1.\n",
        "% @query unknown { q(X) } = { d }\n",
    ),
]


@pytest.mark.parametrize(("name", "program", "contract"), _ADMITTED, ids=[r[0] for r in _ADMITTED])
def test_an_admitted_query_answers_the_program_and_not_its_show_directives(
    tmp_path: Path, name: str, program: str, contract: str
) -> None:
    """The guarantee, differentially: for a query the gate admits, the answer computed off the shown
    projection is the answer computed off the answer sets themselves.

    The control is the same case with every ``#show`` line removed. That program shows every atom,
    so its projection is the identity and its answer is the Gelfond–Kahl answer by construction —
    which is what makes this a check on the projection rather than a second implementation of the
    three-valued rule, written by the same hand that wrote the first.
    """
    restricted = f"% @expect sat\n{contract}{program}"
    unrestricted = _SHOW.sub("", restricted)
    assert unrestricted != restricted, "the control must actually strip something"

    verdict, messages = _answer(tmp_path, f"{name}.lp", restricted)
    control_verdict, control_messages = _answer(tmp_path, f"{name}-control.lp", unrestricted)

    assert verdict is control_verdict is Verdict.PASS, (messages, control_messages)
    assert messages == control_messages
