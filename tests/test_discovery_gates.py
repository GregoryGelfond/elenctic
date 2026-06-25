"""The §2.2-rule-4 preconditions + the R1 theory-presence gate, over ProgramFacts (R1/R2/R4).

These check the gates in isolation against constructed ProgramFacts — the pure precondition layer,
independent of the discovery walk (which wires them in B1)."""

from pathlib import Path

import pytest

from elenctic.discovery import DiscoveryError, check_program
from elenctic.expectation import parse
from elenctic.program import ProgramFacts

WHERE = Path("case.lp")


def _facts(
    *,
    theory: bool = False,
    shown: frozenset[str] = frozenset(),
    opt: bool = False,
    maxi: bool = False,
) -> ProgramFacts:
    return ProgramFacts(
        has_theory_atom=theory, shown=shown, has_optimization=opt, has_maximize=maxi
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


def test_r2_cost_over_maximize_is_loud_the_silent_miscompile_guard() -> None:
    # The GATING case: a #maximize in the (resolved) library would skip this if we scanned the text.
    exp = parse("% @expect sat\n% @cost { 3 }\n")
    with pytest.raises(DiscoveryError, match=r"@cost over a #maximize"):
        check_program(exp, _facts(opt=True, maxi=True), "clingo", WHERE)


def test_r2_no_query_needs_the_contrary_shown() -> None:
    exp = parse("% @expect sat\n% @query no { reachable(a) }\n")
    with pytest.raises(DiscoveryError, match=r"contrary literal.*-reachable"):
        check_program(exp, _facts(shown=frozenset({"reachable"})), "clingo", WHERE)


def test_a_clean_program_passes_all_gates() -> None:
    # A theory-free Sat contract with an optimizing encoding under clingo: no gate fires.
    exp = parse("% @expect sat\n% @optimal { a }\n")
    check_program(exp, _facts(opt=True), "clingo", WHERE)  # no raise


def test_unsat_contract_skips_the_model_bearing_gates() -> None:
    # @expect unsat carries no model-bearing tag, so only R1 (program-side, theory-agnostic) fires.
    exp = parse("% @expect unsat\n")
    check_program(exp, _facts(), "clingo", WHERE)  # no raise
