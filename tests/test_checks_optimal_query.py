"""Unit tests for the optimal-base checks and the ``@query`` check.

The optimal-base modes aggregate over ``ConsistentOptimalEnumeration``'s ``optimal_observables``
(the ``--opt-mode=optN`` solve). The ``@query`` check is errata-corrected (Def 2.2.2): a
singleton ground query reads the cautious consequences ⋂; a *conjunctive* (n≥2) ground query reads
the model census; a yes/no binding reads ⋂; an unknown binding reads ⋂ and ⋃. Every arm short-
circuits: ``Inconsistent`` (AS(P)=∅) → FAIL (every query is vacuously yes-and-no). A
misroute is a ``SeamError``, never a costumed verdict. Pure over a ``Determination``.
"""

import pytest
from clingo import Symbol, parse_term

from elenctic.checks import (
    Check,
    assign_optimal_contains,
    brave_optimal_contains,
    cautious_optimal_contains,
    count_optimal_is,
    has_optimal_model,
    query_matches,
)
from elenctic.expectation import WitnessClaim
from elenctic.query import Answer, BindingQuery, GroundQuery, QueryLiteral, Var
from elenctic.result import (
    ConsistentCautious,
    ConsistentEnumeration,
    ConsistentOptimalEnumeration,
    Inconclusive,
    Inconsistent,
    Observable,
    Optimum,
    SeamError,
    Verdict,
)
from support import decided


def obs(*names: str) -> Observable:
    return Observable(frozenset(parse_term(name) for name in names))


def lits(*names: str) -> frozenset[Symbol]:
    return frozenset(parse_term(name) for name in names)


def wm(*names: str) -> WitnessClaim:
    return WitnessClaim(shown=lits(*names))


def opt_enum(*observables: Observable) -> ConsistentOptimalEnumeration:
    return ConsistentOptimalEnumeration(observables, Optimum((0,)))


def enum(*observables: Observable) -> ConsistentEnumeration:
    return ConsistentEnumeration(observables)


@pytest.mark.parametrize(
    ("check", "label"),
    [
        pytest.param(has_optimal_model(wm("a"), line=1), "@optimal", id="optimal"),
        pytest.param(
            cautious_optimal_contains(lits("a"), line=1), "@cautious optimal", id="cautious-optimal"
        ),
        pytest.param(
            brave_optimal_contains(lits("a"), line=1), "@brave optimal", id="brave-optimal"
        ),
        pytest.param(count_optimal_is(1, line=1), "@count optimal", id="count-optimal"),
        pytest.param(
            query_matches(GroundQuery(Answer.yes, (parse_term("a"),)), line=1), "@query", id="query"
        ),
    ],
)
def test_undecided_when_inconclusive(check: Check, label: str) -> None:
    report = check(decided(Inconclusive()))
    assert report.verdict is Verdict.UNDECIDED  # a timeout is never FAIL
    assert report.label == label


def test_optimal_base_checks_share_the_optimal_observables() -> None:
    result = opt_enum(obs("a", "x"), obs("a", "y"))
    assert has_optimal_model(wm("a", "x"), line=1)(decided(result)).verdict is Verdict.PASS
    assert (
        cautious_optimal_contains(lits("a"), line=1)(decided(result)).verdict is Verdict.PASS
    )  # optimal backbone
    missing = cautious_optimal_contains(lits("x"), line=1)(decided(result))
    assert missing.verdict is Verdict.FAIL  # x is in only one optimum
    assert "x" in missing.message
    assert "⋂" in missing.message
    assert brave_optimal_contains(lits("y"), line=1)(decided(result)).verdict is Verdict.PASS
    assert count_optimal_is(2, line=1)(decided(result)).verdict is Verdict.PASS


def test_optimal_base_is_total_on_unsat() -> None:
    assert has_optimal_model(wm("a"), line=1)(decided(Inconsistent())).verdict is Verdict.FAIL
    assert (
        cautious_optimal_contains(lits("a"), line=1)(decided(Inconsistent())).verdict
        is Verdict.FAIL
    )
    assert (
        brave_optimal_contains(lits("a"), line=1)(decided(Inconsistent())).verdict is Verdict.FAIL
    )
    assert count_optimal_is(2, line=1)(decided(Inconsistent())).verdict is Verdict.FAIL
    assert (
        count_optimal_is(0, line=1)(decided(Inconsistent())).verdict is Verdict.PASS
    )  # @count optimal 0 over ∅


def test_optimal_base_singleton_class() -> None:
    # ⋂ Opt(P) = ⋃ Opt(P) = the single optimal model (the family[0].∩(*[]) edge).
    result = opt_enum(obs("a", "x"))
    assert has_optimal_model(wm("a", "x"), line=1)(decided(result)).verdict is Verdict.PASS
    assert (
        cautious_optimal_contains(lits("a", "x"), line=1)(decided(result)).verdict is Verdict.PASS
    )
    assert brave_optimal_contains(lits("x"), line=1)(decided(result)).verdict is Verdict.PASS


def test_optimal_base_failures_name_opt_p_not_enumerated_models() -> None:
    result = opt_enum(obs("a", "x"), obs("a", "y"))
    partial = has_optimal_model(wm("a"), line=1)(decided(result))  # subset, not the whole model
    assert partial.verdict is Verdict.FAIL
    assert "optimal" in partial.message  # names Opt(P), not "enumerated models"
    assert "enumerated models" not in partial.message
    brave_miss = brave_optimal_contains(lits("z"), line=1)(decided(result))
    assert brave_miss.verdict is Verdict.FAIL
    assert "z" in brave_miss.message
    assert "⋃" in brave_miss.message


# --- @query: ground singleton (⋂), ground conjunctive (census), binding (⋂, and ⋃ for unknown) ---


def test_query_ground_conjunctive_reads_the_census_and_localizes() -> None:
    asked = query_matches(
        GroundQuery(Answer.yes, (parse_term("start(s)"), parse_term("end(t)"))), line=1
    )
    both = asked(
        decided(enum(obs("start(s)", "end(t)")))
    )  # both conjuncts true in all → computed yes
    assert both.verdict is Verdict.PASS
    missed = asked(
        decided(enum(obs("start(s)")))
    )  # end(t) not in the census → computed unknown ≠ yes
    assert missed.verdict is Verdict.FAIL
    assert "yes" in missed.message, "the answer the contract claimed"
    assert "unknown" in missed.message, "and the answer the census supports"
    assert "end(t)" in missed.message  # localizes the not-entailed conjunct


def test_query_ground_conjunctive_no_localizes_from_the_census() -> None:
    # each model falsifies a *different* conjunct → computed "no" (∀M ∃i: l̄i∈M); ⋂ is empty here,
    # so the localization MUST come from the census, not ⋂ (the regression fence for the
    # "(counter-entailed: { })" defect).
    asked = query_matches(GroundQuery(Answer.yes, (parse_term("p(a)"), parse_term("p(b)"))), line=1)
    missed = asked(decided(enum(obs("p(a)", "-p(b)"), obs("-p(a)", "p(b)"))))
    assert missed.verdict is Verdict.FAIL  # expected yes, computed no
    assert "no" in missed.message
    assert "falsified" in missed.message  # census-based, not an empty counter-entailed set
    # Both conjuncts are named, because each is falsified in some model and neither alone explains
    # the "no": the localization has to come from the census.
    assert "p(a)" in missed.message
    assert "p(b)" in missed.message


def test_query_ground_singleton_no_via_strong_negation() -> None:
    asked = query_matches(GroundQuery(Answer.no, (parse_term("reachable(x)"),)), line=1)
    # contrary -reachable(x) entailed ⇒ computed no (Def 2.2.2)
    assert asked(decided(ConsistentCautious(lits("-reachable(x)")))).verdict is Verdict.PASS
    # mere absence is not falsity ⇒ computed unknown ≠ no ⇒ FAIL
    assert asked(decided(ConsistentCautious(lits("other")))).verdict is Verdict.FAIL


def test_query_short_circuits_to_fail_on_unsat() -> None:
    asked = query_matches(GroundQuery(Answer.yes, (parse_term("start(s)"),)), line=1)
    short = asked(decided(Inconsistent()))
    assert short.verdict is Verdict.FAIL  # AS(P) = ∅: every query vacuously yes-and-no
    assert "∅" in short.message


def test_query_binding_yes_reads_cautious() -> None:
    asked = query_matches(
        BindingQuery(
            Answer.yes,
            QueryLiteral("reachable", True, (Var("X"),)),
            frozenset({(parse_term("s"),), (parse_term("a"),)}),
        ),
        line=1,
    )
    assert (
        asked(decided(ConsistentCautious(lits("reachable(s)", "reachable(a)")))).verdict
        is Verdict.PASS
    )
    missed = asked(decided(ConsistentCautious(lits("reachable(s)"))))
    assert missed.verdict is Verdict.FAIL  # computed { (s) } ≠ contract { (s), (a) }
    assert "reachable" in missed.message  # the goal is surfaced
    assert asked(decided(Inconsistent())).verdict is Verdict.FAIL  # AS(P) = ∅ short-circuit


def test_query_binding_no_via_contrary() -> None:
    asked = query_matches(
        BindingQuery(
            Answer.no,
            QueryLiteral("blocked", True, (Var("X"),)),
            frozenset({(parse_term("a"),)}),
        ),
        line=1,
    )
    # -blocked(a) entailed ⇒ the no-binding set is { (a) }
    assert asked(decided(ConsistentCautious(lits("-blocked(a)")))).verdict is Verdict.PASS


def test_query_binding_unknown_reads_brave_from_the_enumeration() -> None:
    asked = query_matches(
        BindingQuery(
            Answer.unknown,
            QueryLiteral("reachable", True, (Var("X"),)),
            frozenset({(parse_term("b"),)}),
        ),
        line=1,
    )
    # census {reachable(s), reachable(b)}, {reachable(s)} → ⋂ = {reachable(s)}, ⋃ adds reachable(b);
    # brave domain { s, b } − yes { s } − no { } = { b }; the contract asserts unknown = { b }
    result = enum(obs("reachable(s)", "reachable(b)"), obs("reachable(s)"))
    assert asked(decided(result)).verdict is Verdict.PASS


def test_query_binding_unknown_off_a_cautious_only_shape_raises_seam_error() -> None:
    # the wiring rule routes an unknown binding to a brave-bearing run; handing it a cautious-only
    # shape is an elenctic bug — a SeamError, never a costumed verdict (the accessor seam).
    asked = query_matches(
        BindingQuery(
            Answer.unknown,
            QueryLiteral("reachable", True, (Var("X"),)),
            frozenset({(parse_term("b"),)}),
        ),
        line=1,
    )
    with pytest.raises(SeamError):
        asked(decided(ConsistentCautious(lits("reachable(s)"))))


def test_assign_optimal_contains_reads_the_optimal_assignment() -> None:
    # @assign optimal { A }: some optimal model's theory assignment contains A. Reads the full
    # optimal census (the assignment dimension), so it suppresses projection.
    want = frozenset({(parse_term("w"), 2)})
    carrying = opt_enum(Observable(frozenset({parse_term("a")}), frozenset({(parse_term("w"), 2)})))
    missing = opt_enum(Observable(frozenset({parse_term("a")}), frozenset({(parse_term("w"), 9)})))
    assert assign_optimal_contains(want, line=1)(decided(carrying)).verdict is Verdict.PASS
    assert assign_optimal_contains(want, line=1)(decided(missing)).verdict is Verdict.FAIL
    assert assign_optimal_contains(want, line=1)(decided(Inconsistent())).verdict is Verdict.FAIL
    assert (
        assign_optimal_contains(want, line=1)(decided(Inconclusive())).verdict is Verdict.UNDECIDED
    )
