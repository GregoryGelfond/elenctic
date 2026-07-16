"""The preconditions + the theory-presence gate, over ProgramFacts.

These check the gates in isolation against constructed ProgramFacts — the pure precondition layer,
independent of the discovery walk that wires them in."""

from pathlib import Path

import pytest

from elenctic.discovery import DiscoveryError, check_program
from elenctic.expectation import parse
from elenctic.program import ProgramFacts

WHERE = Path("case.lp")


def _facts(
    *,
    theory: bool = False,
    shown: frozenset[tuple[str, int]] = frozenset(),
    opt: bool = False,
    maxi: bool = False,
    theory_opt: bool = False,
) -> ProgramFacts:
    return ProgramFacts(
        has_theory_atom=theory,
        shown=shown,
        has_optimization=opt,
        has_maximize=maxi,
        has_theory_optimization=theory_opt,
        sources=frozenset(),  # check_program does not read sources (hygiene-only); empty is fine
    )


def test_r1_theory_atom_under_clingo_is_loud() -> None:
    # A theory atom in the resolved program under a (default/declared) clingo solver → loud refusal,
    # no verdict. Theory-agnostic (presence, never identity).
    exp = parse("% @expect sat\n")
    with pytest.raises(DiscoveryError, match=r"theory atom.*clingo.*@elenctic solver clingcon"):
        check_program(exp, _facts(theory=True), "clingo", WHERE)


def test_r1_theory_atom_under_clingcon_is_allowed() -> None:
    exp = parse("% @expect sat\n")
    check_program(exp, _facts(theory=True), "clingcon", WHERE)  # no raise


def test_r4_theory_contract_under_clingo_is_loud() -> None:
    # The contract-side dual: @assign reads the theory half, but the program is theory-free and the
    # solver is clingo → an empty assignment would mis-evaluate. Loud.
    exp = parse("% @expect sat\n% @assign { x=1 }\n")
    with pytest.raises(DiscoveryError, match=r"theory binding.*needs a theory solver"):
        check_program(exp, _facts(), "clingo", WHERE)


def test_r2_optimal_base_needs_an_optimizing_encoding() -> None:
    exp = parse("% @expect sat\n% @optimal { a }\n")
    with pytest.raises(DiscoveryError, match=r"optimizing encoding"):
        check_program(exp, _facts(opt=False), "clingo", WHERE)


def test_a_bare_as_p_tag_over_a_theory_objective_is_loud() -> None:
    # The converse of the optimizing-encoding gate, and the reason it needs one: clingo's
    # --opt-mode=ignore switches off *clingo's* optimize statements, but a clingcon &minimize is a
    # theory atom its own propagator drives, so the AS(P) modes cannot switch it off. They would
    # read a pruned model stream and answer a different question, silently. Refuse instead.
    exp = parse("% @expect sat\n% @cautious { a }\n")
    with pytest.raises(DiscoveryError, match=r"&minimize.*AS\(P\)|theory objective"):
        check_program(exp, _facts(theory=True, theory_opt=True), "clingcon", WHERE)


def test_every_bare_as_p_tag_is_caught_over_a_theory_objective() -> None:
    # The gate keys on the contract reading AS(P), not on one tag: every tag that rides an AS(P)
    # run is refused, including @query, which reaches AS(P) by two different routes.
    for contract in (
        "% @expect sat\n% @count 2\n",
        "% @expect sat\n% @model { a }\n",
        "% @expect sat\n% @cautious { a }\n",
        "% @expect sat\n% @brave { a }\n",
        "% @expect sat\n% @query yes { a }\n",
        "% @expect sat\n% @query yes { a, b }\n",
    ):
        with pytest.raises(DiscoveryError, match=r"&minimize"):
            check_program(parse(contract), _facts(theory=True, theory_opt=True), "clingcon", WHERE)


def test_expect_sat_alone_over_a_theory_objective_is_allowed() -> None:
    # @expect sat reads only whether an answer set exists. A theory objective ranks answer sets
    # without removing any, so it cannot change that: there is nothing to refuse.
    exp = parse("% @expect sat\n")
    check_program(exp, _facts(theory=True, theory_opt=True), "clingcon", WHERE)


def test_a_bare_as_p_tag_without_a_theory_objective_is_allowed() -> None:
    # The gate is scoped to the theory objective. A bare AS(P) tag over a clingo #minimize is fine:
    # --opt-mode=ignore does switch that off, which is the whole point of stating it.
    exp = parse("% @expect sat\n% @cautious { a }\n")
    check_program(exp, _facts(theory=True, opt=True), "clingcon", WHERE)


def test_r2_cost_over_maximize_is_loud_the_silent_miscompile_guard() -> None:
    # The GATING case: a #maximize in the (resolved) library would skip this if we scanned the text.
    exp = parse("% @expect sat\n% @cost { 3 }\n")
    with pytest.raises(DiscoveryError, match=r"@cost over a #maximize"):
        check_program(exp, _facts(opt=True, maxi=True), "clingo", WHERE)


def test_r2_no_query_needs_the_contrary_shown() -> None:
    exp = parse("% @expect sat\n% @query no { reachable(a) }\n")
    with pytest.raises(DiscoveryError, match=r"contrary literal.*-reachable"):
        check_program(exp, _facts(shown=frozenset({("reachable", 1)})), "clingo", WHERE)


def test_a_clean_program_passes_all_gates() -> None:
    # A theory-free Sat contract with an optimizing encoding under clingo: no gate fires.
    exp = parse("% @expect sat\n% @optimal { a }\n")
    check_program(exp, _facts(opt=True), "clingo", WHERE)  # no raise


def test_unsat_contract_skips_the_model_bearing_gates() -> None:
    # @expect unsat carries no model-bearing tag, so only the program-side theory gate fires.
    exp = parse("% @expect unsat\n")
    check_program(exp, _facts(), "clingo", WHERE)  # no raise


# The contrary precondition per @query form (_contraries_needed): which forms read a contrary off
# ⋂/⋃ and so require it shown. `shown=∅` here, so any required contrary is absent → loud.
@pytest.mark.parametrize(
    ("query_tag", "needs_contrary"),
    [
        pytest.param("@query no { reachable(x) }", True, id="ground-no"),
        pytest.param("@query unknown { reachable(x) }", True, id="ground-unknown"),
        pytest.param("@query no { reachable(X) } = { a }", True, id="binding-no-nonempty"),
        pytest.param("@query unknown { reachable(X) } = { a }", True, id="binding-unknown"),
        pytest.param("@query no { -reachable(x) }", True, id="ground-no-strong-neg"),
        # a binding goal `-reachable` reads its positive contrary `reachable` off ⋃/⋂ (the
        # _goal_contrary_name negative-goal branch) — needs `reachable` shown.
        pytest.param("@query no { -reachable(X) } = { a }", True, id="binding-no-strong-neg"),
        pytest.param("@query no { reachable(X) } = { }", False, id="empty-no-carveout"),
        pytest.param("@query yes { reachable(x) }", False, id="yes-reads-positive"),
    ],
)
def test_contrary_precondition_per_query_form(query_tag: str, needs_contrary: bool) -> None:
    exp = parse(f"% @expect sat\n% {query_tag}\n")
    if needs_contrary:
        with pytest.raises(DiscoveryError, match=r"contrary|reachable"):
            check_program(exp, _facts(), "clingo", WHERE)
    else:
        check_program(exp, _facts(), "clingo", WHERE)  # vacuous / positive-reading → no contrary


def test_contrary_precondition_passes_when_the_contrary_is_shown() -> None:
    exp = parse("% @expect sat\n% @query no { reachable(x) }\n")
    shown = frozenset({("reachable", 1), ("-reachable", 1)})
    check_program(exp, _facts(shown=shown), "clingo", WHERE)


def test_binding_query_with_a_wrong_arity_contrary_is_loud() -> None:
    # The arity-aware closure on the highest-risk path (binding @query, via goal.arity): a goal
    # whose contrary is shown at the WRONG arity is unobservable, so it must be loud. reachable(X)
    # needs -reachable/1; a -reachable/2 (a typo) does not satisfy it.
    exp = parse("% @expect sat\n% @query unknown { reachable(X) } = { a }\n")
    shown = frozenset({("reachable", 1), ("-reachable", 2)})
    with pytest.raises(DiscoveryError, match=r"-reachable/1"):
        check_program(exp, _facts(shown=shown), "clingo", WHERE)
