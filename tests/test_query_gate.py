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
from elenctic.program import Restricted, Unrestricted
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


_WRONG_PASS_ROUTES = [
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
    # A signature the program DISPLAYS with a `#show <term> : <body>.` directive rather than
    # declaring. The term reaches the output whenever the body holds, so it can arrive for a
    # symbol no answer set contains at all — `winner(alice)` here is in none.
    (
        "displayed-not-declared",
        "% @expect sat\n% @query yes { winner(alice) }\nscored(alice,3).\n"
        "#show winner(N) : scored(N,S), S > 2.\n",
    ),
    # The same, where the signature is ALSO declared — so a check that only asked whether the
    # vocabulary covers the query would admit it.
    (
        "displayed-and-declared",
        "% @expect sat\n% @query yes { q(b) }\nr(a). q(a).\n"
        "#show q/1.\n#show -q/1.\n#show q(b) : r(a).\n",
    ),
]


@pytest.mark.parametrize(
    ("name", "body"), _WRONG_PASS_ROUTES, ids=[r[0] for r in _WRONG_PASS_ROUTES]
)
def test_a_query_the_program_cannot_answer_is_refused_not_certified(
    tmp_path: Path, name: str, body: str
) -> None:
    with pytest.raises(DiscoveryError, match=r"this @query reads"):
        discover(_write(tmp_path, f"{name}.lp", body))


@pytest.mark.parametrize(
    ("name", "body"), _WRONG_PASS_ROUTES, ids=[r[0] for r in _WRONG_PASS_ROUTES]
)
def test_each_refused_case_really_does_state_something_false(
    tmp_path: Path, name: str, body: str
) -> None:
    """Every contract above is refused. This is what establishes that each one *deserved* to be.

    A test that asserts an input is rejected proves nothing about the input: it passes just as well
    over a contract that was true all along, and it would then be defending an over-refusal while
    reading as a wrong-answer guard. So each body is re-run with its `#show` lines stripped — a
    program that shows every atom, whose projection is the identity — and the claim must **FAIL**
    there. That is the measurement that the claim is false, rather than a comment saying so.
    """
    verdict, messages = _answer(tmp_path, f"{name}-control.lp", _SHOW.sub("", body))
    assert verdict is Verdict.FAIL, (
        f"{name}: the contract passes against a program that hides nothing, so this fixture is not "
        f"a false claim and the refusal above is an over-refusal. {messages}"
    )


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
    with pytest.raises(
        DiscoveryError, match=r"displays with a `#show <term> : <body>\.` directive"
    ):
        discover(_write(tmp_path, "conditional.lp", body))


# --- the guarantee itself, as a differential ---

_HIDDEN = "hidden(1). -hidden(2).\n"
"""A distractor every row carries, and the reason the differential is not comparing a case to
itself: the control below strips the ``#show`` lines, so the two sides differ only where the
restriction actually withholds an atom. A row whose program has nothing outside its shown vocabulary
is a row where the projection is *already* the identity — the case and its control are then the same
program written twice, and it would pass against an implementation that projects nothing at all."""

_ADMITTED = [
    # (name, program, contract) — each declares exactly what its query reads, and each hides
    # something it does not.
    (
        "singleton-yes",
        f"p(x). -q(x). {_HIDDEN}#show p/1.\n#show -p/1.\n",
        "% @query yes { p(x) }\n",
    ),
    (
        "singleton-no",
        f"p(x). -q(x). {_HIDDEN}#show q/1.\n#show -q/1.\n",
        "% @query no { q(x) }\n",
    ),
    (
        "singleton-unknown",
        f"{{ r(x) }}. {_HIDDEN}#show r/1.\n#show -r/1.\n",
        "% @query unknown { r(x) }\n",
    ),
    (
        "conjunctive-yes",
        f"p(x). q(x). {_HIDDEN}#show p/1.\n#show -p/1.\n#show q/1.\n#show -q/1.\n",
        "% @query yes { p(x), q(x) }\n",
    ),
    (
        "conjunctive-no",
        f"-p(x). -q(x). {_HIDDEN}#show p/1.\n#show -p/1.\n#show q/1.\n#show -q/1.\n",
        "% @query no { p(x), q(x) }\n",
    ),
    # The corrected Def 2.2.2 "no" is `∀M ∃i: l̄i ∈ M`, where each answer set may falsify a
    # *different* conjunct — the reading the published errata fixed, and the one the old `∃i ∀M`
    # form gets wrong. Over a one-model census the two are indistinguishable, so every row above
    # would pass against either. Here three answer sets falsify by different conjuncts: {-p,-q},
    # {p,-q} by q, {-p,q} by p. This is also the only row whose census has more than one member,
    # so it is the only one where the projection has a *set* to collapse.
    (
        "conjunctive-no-per-model",
        "{ p(x) }. { q(x) }.\n-p(x) :- not p(x).\n-q(x) :- not q(x).\n:- p(x), q(x).\n"
        f"{_HIDDEN}#show p/1.\n#show -p/1.\n#show q/1.\n#show -q/1.\n",
        "% @query no { p(x), q(x) }\n",
    ),
    (
        "binding-yes",
        f"q(a). q(b). -q(c). {_HIDDEN}#show q/1.\n",
        "% @query yes { q(X) } = { a, b }\n",
    ),
    (
        "binding-no",
        f"q(a). -q(c). {_HIDDEN}#show -q/1.\n",
        "% @query no { q(X) } = { c }\n",
    ),
    (
        "binding-unknown",
        f"q(a). -q(c). {{ q(d) }}. {_HIDDEN}#show q/1.\n#show -q/1.\n",
        "% @query unknown { q(X) } = { d }\n",
    ),
    # Arity, on both axes a one-argument unary goal cannot separate: a signature carries the goal's
    # ARGUMENT count while its binding tuples carry its distinct-VARIABLE count, and `link(X, X)` is
    # where those two numbers differ.
    (
        "binding-yes-arity-2",
        f"link(a,b). link(a,c). -link(b,a). {_HIDDEN}#show link/2.\n",
        "% @query yes { link(X, Y) } = { (a,b), (a,c) }\n",
    ),
    (
        "binding-yes-repeated-variable",
        f"link(a,a). link(a,b). {_HIDDEN}#show link/2.\n",
        "% @query yes { link(X, X) } = { a }\n",
    ),
    (
        "singleton-yes-0-arity",
        f"settled. {_HIDDEN}#show settled/0.\n#show -settled/0.\n",
        "% @query yes { settled }\n",
    ),
    # A conjunction whose conjuncts differ in arity and in sign.
    (
        "conjunctive-yes-mixed",
        f"settled. -link(a,b). {_HIDDEN}"
        "#show settled/0.\n#show -settled/0.\n#show link/2.\n#show -link/2.\n",
        "% @query yes { settled, -link(a,b) }\n",
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

    # The fixture's own property, asserted rather than intended: the restricted side must really
    # withhold an atom, or the two sides are the same program written twice and the comparison
    # below holds for an implementation that projects nothing at all.
    (case,) = discover(_write(tmp_path, f"{name}.lp", restricted))
    (control,) = discover(_write(tmp_path, f"{name}-control.lp", unrestricted))
    assert isinstance(case.shown, Restricted), case.shown
    assert isinstance(control.shown, Unrestricted), control.shown
    assert ("hidden", 1) not in case.shown.signatures, (
        f"{name}: the distractor is inside the shown vocabulary, so this row hides nothing"
    )

    verdict, messages = _answer(tmp_path, f"{name}.lp", restricted)
    control_verdict, control_messages = _answer(tmp_path, f"{name}-control.lp", unrestricted)

    assert verdict is control_verdict is Verdict.PASS, (messages, control_messages)
    assert messages == control_messages
