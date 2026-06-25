"""@elenctic solver: the declared frame (R7), well-formedness (R10), and membership (R5)."""

import pytest

from elenctic.expectation import ContractError, Sat, parse, parse_contract


def test_declares_the_solver() -> None:
    contract = parse_contract(
        "% @expect sat\n% @elenctic solver clingcon\n&sum { x } >= 1.\n", source="case.lp"
    )
    assert contract.solver == "clingcon"
    assert isinstance(contract.expectation, Sat)


def test_absent_directive_leaves_solver_undeclared() -> None:
    # None = undeclared; discovery defaults it to "clingo" (the stated default, R1).
    contract = parse_contract("% @expect sat\n% @model { a }\na.\n", source="case.lp")
    assert contract.solver is None


def test_unknown_solver_is_a_contract_error_with_provenance() -> None:  # R5
    pattern = r"case\.lp:1:.*unknown solver 'gringo'.*clingcon, clingo"
    with pytest.raises(ContractError, match=pattern):
        parse_contract("% @elenctic solver gringo\n% @expect sat\n", source="case.lp")


def test_repeated_solver_directive_is_a_contract_error() -> None:  # R10 (single-valued)
    with pytest.raises(ContractError, match=r"at most one @elenctic solver"):
        parse_contract(
            "% @elenctic solver clingo\n% @elenctic solver clingcon\n% @expect sat\n",
            source="case.lp",
        )


def test_empty_solver_payload_is_a_contract_error() -> None:  # R10
    with pytest.raises(ContractError, match=r"@elenctic solver needs a solver name"):
        parse_contract("% @elenctic solver\n% @expect sat\n", source="case.lp")


def test_unknown_elenctic_subdirective_is_a_contract_error() -> None:  # R10
    with pytest.raises(ContractError, match=r"unknown @elenctic directive 'budget'"):
        parse_contract("% @elenctic budget 5\n% @expect sat\n", source="case.lp")


def test_behavioral_parse_is_unchanged_by_the_directive() -> None:
    # @elenctic does NOT thread through the behavioral builder (R9): it is routed away.
    with_directive = parse_contract(
        "% @expect sat\n% @model { a }\n% @elenctic solver clingo\na.\n"
    )
    without = parse_contract("% @expect sat\n% @model { a }\na.\n")
    assert with_directive.expectation == without.expectation


def test_elenctic_is_never_reported_as_an_unknown_contract_tag() -> None:
    # Regression (A1-A3 review): @elenctic is routed away before the behavioral closed-vocab check,
    # so it must never surface as "unknown contract tag: @elenctic" (a real @word typo still does).
    parse("% @expect sat\n% @elenctic solver clingo\n")  # no raise
    with pytest.raises(ContractError, match=r"unknown contract tag: @bogus"):
        parse("% @expect sat\n% @bogus thing\n")
