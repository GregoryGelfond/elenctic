"""``expectation.parse`` — the well-formedness gate (spec §2.2). Every ill-formed block is
rejected with a ``ContractError`` that names what is wrong (and, with a ``source``, where).
The precondition rules of §2.2 rule 4 (optimization/clingcon/contrary-shown) need the
encoding and are checked at discovery (spec §5), not here."""

import pytest

from elenctic.expectation import ContractError, Sat, Unsat, parse


@pytest.mark.parametrize(
    ("text", "match"),
    [
        # rule 1 — exactly one @expect.
        pytest.param("% @model { a }\n", r"@expect", id="missing-expect"),
        pytest.param("% @expect sat\n% @expect sat\n", r"one @expect", id="two-expect"),
        pytest.param("% @expect maybe\n", r"sat\|unsat", id="expect-bad-value"),
        # rule 2 — single-valued witness/scalar cells (per (mode, base)).
        pytest.param(
            "% @expect sat\n% @model { a }\n% @model { b }\n", r"@model", id="two-model-all"
        ),
        pytest.param(
            "% @expect sat\n% @model optimal { a }\n% @model optimal { b }\n",
            r"optimal",
            id="two-model-optimal",
        ),
        pytest.param(
            "% @expect sat\n% @optimal { a }\n% @model optimal { b }\n",
            r"optimal",
            id="optimal-and-model-optimal-are-one-cell",
        ),
        pytest.param("% @expect sat\n% @cost { 1 }\n% @cost { 2 }\n", r"@cost", id="two-cost"),
        pytest.param(
            "% @expect sat\n% @assign { v=1 }\n% @assign { v=2 }\n", r"@assign", id="two-assign"
        ),
        pytest.param("% @expect sat\n% @count 1\n% @count 2\n", r"@count", id="two-count-all"),
        pytest.param(
            "% @expect sat\n% @count optimal 1\n% @count optimal 2\n",
            r"@count optimal",
            id="two-count-optimal",
        ),
        # rule 3 — satisfiability and count consistency.
        pytest.param("% @expect unsat\n% @model { a }\n", r"unsat", id="unsat-with-model"),
        pytest.param("% @expect unsat\n% @cautious { a }\n", r"unsat", id="unsat-with-cautious"),
        pytest.param("% @expect unsat\n% @brave { a }\n", r"unsat", id="unsat-with-brave"),
        pytest.param("% @expect unsat\n% @cost { 1 }\n", r"unsat", id="unsat-with-cost"),
        pytest.param("% @expect unsat\n% @assign { v=1 }\n", r"unsat", id="unsat-with-assign"),
        pytest.param("% @expect unsat\n% @query yes { a }\n", r"unsat", id="unsat-with-query"),
        pytest.param("% @expect unsat\n% @count 2\n", r"unsat", id="unsat-with-positive-count"),
        pytest.param("% @expect sat\n% @count 0\n", r"unsat", id="sat-with-zero-count"),
        pytest.param(
            "% @expect sat\n% @count optimal 0\n", r"unsat", id="sat-with-zero-count-optimal"
        ),
        pytest.param(
            "% @expect sat\n% @count 2\n% @count optimal 3\n",
            r"m ≤ n",
            id="count-optimal-exceeds-count",
        ),
        # rule 5 — @query shape (delegated to query.parse_query, wrapped as ContractError).
        pytest.param("% @expect sat\n% @query maybe { a }\n", r"answer", id="query-bad-answer"),
        pytest.param("% @expect sat\n% @query yes\n", r"@query", id="query-no-payload"),
        pytest.param(
            "% @expect sat\n% @query yes { path(X, a, Y) } = { (s, t) }\n",
            r"all-variable",
            id="query-partially-ground",
        ),
        # malformed payloads — rejected by the term/litset layer, surfaced as ContractError.
        pytest.param("% @expect sat\n% @model { }\n", r"at least one literal", id="empty-litset"),
        pytest.param(
            "% @expect sat\n% @model { a, 1 }\n", r"must be literals", id="non-literal-in-litset"
        ),
        pytest.param("% @expect sat\n% @cost { a }\n", r"@cost", id="non-int-cost"),
        pytest.param("% @expect sat\n% @count x\n", r"@count", id="non-int-count"),
        pytest.param("% @expect sat\n% @assign { v }\n", r"binding", id="assign-without-equals"),
        # an unknown tag is a loud error, never silently ignored (§2.2).
        pytest.param(
            "% @expect sat\n% @frobnicate { a }\n", r"unknown contract tag", id="unknown-tag"
        ),
        # empty / unclosed / non-ground brace bodies — never a silent empty claim (§2.1 grammar).
        pytest.param("% @expect sat\n% @assign { }\n", r"@assign", id="empty-assign"),
        pytest.param("% @expect sat\n% @assign {}\n", r"@assign", id="empty-assign-no-space"),
        pytest.param("% @expect sat\n% @model { a, b\n", r"litset", id="litset-never-closes"),
        pytest.param(
            "% @expect sat\n% @model { p(X) }\n", r"variable-free", id="variable-in-litset"
        ),
        pytest.param("", r"@expect", id="empty-file-no-contract"),
    ],
)
def test_parse_rejects_ill_formed(text: str, match: str) -> None:
    with pytest.raises(ContractError, match=match):
        parse(text)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "% @expect sat\n% @model { a }\n% @model optimal { b }\n",
            id="model-all-and-optimal-coexist",
        ),
        pytest.param(
            "% @expect sat\n% @count 3\n% @count optimal 2\n", id="count-all-and-optimal-coexist"
        ),
        pytest.param(
            "% @expect sat\n% @cautious { a }\n% @cautious { b }\n", id="cautious-accumulates"
        ),
        pytest.param("% @expect sat\n% @brave { a }\n% @brave { b }\n", id="brave-accumulates"),
        pytest.param(
            "% @expect sat\n% @query yes { a }\n% @query no { -a }\n", id="queries-accumulate"
        ),
        pytest.param(
            "% @expect sat\n% @model { a }\n% @note one\n% @note two\n", id="notes-accumulate"
        ),
        pytest.param("% @expect unsat\n% @count 0\n", id="unsat-with-zero-count"),
        pytest.param("% @expect unsat\n% @count optimal 0\n", id="unsat-with-zero-count-optimal"),
        pytest.param(
            "% @expect unsat\n% @note nothing satisfies the budget\n", id="unsat-note-only"
        ),
    ],
)
def test_parse_accepts_well_formed(text: str) -> None:
    exp = parse(text)
    assert isinstance(exp, Sat | Unsat)  # does not raise; a well-formed Expectation


def test_contract_error_carries_source_and_line() -> None:
    # dx#2: a payload error names the file and the offending tag's line (here, line 2).
    with pytest.raises(ContractError, match=r"cases/x\.lp:2"):
        parse("% @expect sat\n% @model { }\n", source="cases/x.lp")


def test_contract_error_without_source_names_the_line() -> None:
    with pytest.raises(ContractError, match=r"line 2"):
        parse("% @expect sat\n% @model { }\n")


def test_duplicate_cell_error_points_at_the_second_occurrence() -> None:
    # The duplicate @model is on line 3; provenance pins it there, not the first.
    with pytest.raises(ContractError, match=r"x\.lp:3"):
        parse("% @expect sat\n% @model { a }\n% @model { b }\n", source="x.lp")


def test_unsat_error_names_the_offending_model_bearing_tags() -> None:
    # The diagnostic points at the mistake: it names which model-bearing tags conflict with unsat.
    with pytest.raises(ContractError, match=r"@model.*@brave|@brave.*@model"):
        parse("% @expect unsat\n% @model { a }\n% @brave { b }\n")
