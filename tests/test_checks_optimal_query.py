"""Unit tests for the optimal-base checks and the ``@query`` check (spec §3; dx#9).

The optimal-base modes are the all-base aggregations applied to
``optimal_observables`` in place of ``observables`` (the single ``--opt-mode=optN``
solve, §3). The ``@query`` check reads the cautious consequences ⋂ (and the brave
⋃ for an ``unknown`` binding) and short-circuits to ``FAIL`` on ``AS(P) = ∅`` —
where every query is vacuously yes-and-no (§2.2, FR#9). Pure over ``SolveResult``.
"""

import pytest
from clingo import Symbol, parse_term

from elenctic.checks import (
    Check,
    brave_optimal_contains,
    cautious_optimal_contains,
    count_optimal_is,
    has_optimal_model,
    query_matches,
)
from elenctic.query import Answer, BindingQuery, GroundQuery, QueryLiteral, Var
from elenctic.result import Observable, SolveResult, Verdict


def oo(*names: str) -> Observable:
    return Observable(frozenset(parse_term(name) for name in names))


def lits(*names: str) -> frozenset[Symbol]:
    return frozenset(parse_term(name) for name in names)


@pytest.mark.parametrize(
    ("check", "label"),
    [
        pytest.param(has_optimal_model(lits("a")), "@optimal", id="optimal"),
        pytest.param(
            cautious_optimal_contains(lits("a")), "@cautious optimal", id="cautious-optimal"
        ),
        pytest.param(brave_optimal_contains(lits("a")), "@brave optimal", id="brave-optimal"),
        pytest.param(count_optimal_is(1), "@count optimal", id="count-optimal"),
        pytest.param(
            query_matches(GroundQuery(Answer.yes, (parse_term("a"),))), "@query", id="query"
        ),
    ],
)
def test_undecided_when_not_completed(check: Check, label: str) -> None:
    report = check(SolveResult(completed=False))
    assert report.verdict is Verdict.UNDECIDED  # a timeout is never FAIL (§7a)
    assert report.label == label


def test_optimal_base_checks_share_the_optimal_observables() -> None:
    result = SolveResult(True, optimal_observables=(oo("a", "x"), oo("a", "y")))
    assert has_optimal_model(lits("a", "x"))(result).verdict is Verdict.PASS
    assert (
        cautious_optimal_contains(lits("a"))(result).verdict is Verdict.PASS
    )  # a: optimal backbone
    missing = cautious_optimal_contains(lits("x"))(result)
    assert missing.verdict is Verdict.FAIL  # x is in only one optimum
    assert "x" in missing.message and "⋂" in missing.message
    assert brave_optimal_contains(lits("y"))(result).verdict is Verdict.PASS
    assert count_optimal_is(2)(result).verdict is Verdict.PASS


def test_optimal_base_is_total_on_empty() -> None:
    empty = SolveResult(True, optimal_observables=())
    assert has_optimal_model(lits("a"))(empty).verdict is Verdict.FAIL
    assert cautious_optimal_contains(lits("a"))(empty).verdict is Verdict.FAIL
    assert brave_optimal_contains(lits("a"))(empty).verdict is Verdict.FAIL
    assert count_optimal_is(2)(empty).verdict is Verdict.FAIL
    assert count_optimal_is(0)(empty).verdict is Verdict.PASS  # @count optimal 0 over ∅


def test_optimal_base_singleton_class() -> None:
    # ⋂ Opt(P) = ⋃ Opt(P) = the single optimal model (the family[0].∩(*[]) edge).
    result = SolveResult(True, optimal_observables=(oo("a", "x"),))
    assert has_optimal_model(lits("a", "x"))(result).verdict is Verdict.PASS
    assert cautious_optimal_contains(lits("a", "x"))(result).verdict is Verdict.PASS
    assert brave_optimal_contains(lits("x"))(result).verdict is Verdict.PASS


def test_optimal_base_failures_name_opt_p_not_enumerated_models() -> None:
    result = SolveResult(True, optimal_observables=(oo("a", "x"), oo("a", "y")))
    partial = has_optimal_model(lits("a"))(result)  # subset, not the whole model
    assert partial.verdict is Verdict.FAIL
    assert "optimal" in partial.message  # names Opt(P), not "enumerated models" (MAJOR-2)
    assert "enumerated models" not in partial.message
    brave_miss = brave_optimal_contains(lits("z"))(result)
    assert brave_miss.verdict is Verdict.FAIL
    assert "z" in brave_miss.message and "⋃" in brave_miss.message


def test_query_ground_reads_intersection_and_localizes() -> None:
    asked = query_matches(GroundQuery(Answer.yes, (parse_term("start(s)"), parse_term("end(t)"))))
    assert asked(SolveResult(True, intersection=lits("start(s)", "end(t)"))).verdict is Verdict.PASS
    missed = asked(
        SolveResult(True, intersection=lits("start(s)"))
    )  # end(t) not entailed → unknown
    assert missed.verdict is Verdict.FAIL
    assert "yes" in missed.message and "unknown" in missed.message  # expected yes, computed unknown
    assert "end(t)" in missed.message  # dx#9: localizes the not-entailed conjunct (MAJOR-4)


def test_query_ground_no_via_strong_negation() -> None:
    asked = query_matches(GroundQuery(Answer.no, (parse_term("reachable(x)"),)))
    # contrary -reachable(x) entailed ⇒ computed no (Def 2.2.2, §2.1)
    assert asked(SolveResult(True, intersection=lits("-reachable(x)"))).verdict is Verdict.PASS
    # mere absence is not falsity ⇒ computed unknown ≠ no ⇒ FAIL
    assert asked(SolveResult(True, intersection=lits("other"))).verdict is Verdict.FAIL


def test_query_short_circuits_to_fail_on_unsat() -> None:
    asked = query_matches(GroundQuery(Answer.yes, (parse_term("start(s)"),)))
    short = asked(SolveResult(True, intersection=None))
    assert short.verdict is Verdict.FAIL  # AS(P) = ∅: every query is vacuously yes-and-no (§2.2)
    assert "∅" in short.message


def test_query_binding_reads_intersection() -> None:
    asked = query_matches(
        BindingQuery(
            Answer.yes,
            QueryLiteral("reachable", True, (Var("X"),)),
            frozenset({(parse_term("s"),), (parse_term("a"),)}),
        )
    )
    inter = lits("reachable(s)", "reachable(a)")
    assert asked(SolveResult(True, intersection=inter)).verdict is Verdict.PASS
    missed = asked(SolveResult(True, intersection=lits("reachable(s)")))
    assert missed.verdict is Verdict.FAIL  # computed { (s) } ≠ contract { (s), (a) }
    assert "reachable" in missed.message  # the goal is surfaced
    short = asked(SolveResult(True, intersection=None))
    assert short.verdict is Verdict.FAIL  # AS(P) = ∅ short-circuit


def test_query_binding_no_via_contrary() -> None:
    asked = query_matches(
        BindingQuery(
            Answer.no,
            QueryLiteral("blocked", True, (Var("X"),)),
            frozenset({(parse_term("a"),)}),
        )
    )
    inter = lits("-blocked(a)")  # -blocked(a) entailed ⇒ the no-binding set is { (a) }
    assert asked(SolveResult(True, intersection=inter)).verdict is Verdict.PASS


def test_query_binding_unknown_uses_brave_union() -> None:
    asked = query_matches(
        BindingQuery(
            Answer.unknown,
            QueryLiteral("reachable", True, (Var("X"),)),
            frozenset({(parse_term("b"),)}),
        )
    )
    inter = lits("reachable(s)")
    union = lits("reachable(s)", "reachable(b)")
    # brave domain { s, b } − yes { s } − no { } = { b }; the contract asserts unknown = { b }
    assert asked(SolveResult(True, intersection=inter, union=union)).verdict is Verdict.PASS


def test_query_binding_unknown_missing_union_is_total_fail_not_raise() -> None:
    # A misroute (intersection present, ⋃ absent for an unknown binding) must be a total
    # FAIL that names the missing brave consequences — never a raise (MAJOR-1, totality + dx#9).
    asked = query_matches(
        BindingQuery(
            Answer.unknown,
            QueryLiteral("reachable", True, (Var("X"),)),
            frozenset({(parse_term("b"),)}),
        )
    )
    report = asked(SolveResult(True, intersection=lits("reachable(s)"), union=None))
    assert report.verdict is Verdict.FAIL
    assert "⋃" in report.message  # names the missing brave consequences, not a content failure
