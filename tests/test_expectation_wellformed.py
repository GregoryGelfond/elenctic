"""``expectation.parse`` — the well-formedness gate. Every ill-formed block is
rejected with a ``ContractError`` that names what is wrong (and, with a ``source``, where).
The precondition rules (optimization/clingcon/contrary-shown) need the
encoding and are checked at discovery, not here."""

import pytest
from clingo import parse_term

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
        # 1 as well as 2: the unsat shape now *carries* its count, so a positive one slipping past
        # this rule would build a check that reads the census onto a witness solve — a routing
        # fault reported as an elenctic bug, where the author wrote a contract error.
        pytest.param("% @expect unsat\n% @count 1\n", r"unsat", id="unsat-with-count-of-one"),
        pytest.param(
            "% @expect unsat\n% @count optimal 1\n", r"unsat", id="unsat-with-count-optimal-of-one"
        ),
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
        # an unknown tag is a loud error, never silently ignored.
        pytest.param(
            "% @expect sat\n% @frobnicate { a }\n", r"unknown contract tag", id="unknown-tag"
        ),
        # empty / unclosed / non-ground brace bodies — never a silent empty claim.
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
    # a payload error names the file and the offending tag's line (here, line 2).
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


# --- precondition classification (Sat.requires_optimization / requires_theory) ---
# Which encoding capability a contract presupposes. The contract states its precondition here;
# discovery checks it against the encoding (`#minimize`/`#maximize`, clingcon). A different
# predicate from run._has_optimal_base, which excludes bare @cost (it routes @cost's shared solve).


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("% @expect sat\n% @cost { 8 }\n", id="cost"),
        pytest.param("% @expect sat\n% @optimal { a }\n", id="optimal-witness"),
        pytest.param("% @expect sat\n% @cautious optimal { a }\n", id="cautious-optimal"),
        pytest.param("% @expect sat\n% @brave optimal { a }\n", id="brave-optimal"),
        pytest.param("% @expect sat\n% @count optimal 1\n", id="count-optimal"),
    ],
)
def test_requires_optimization_true_for_cost_and_every_optimal_base_tag(text: str) -> None:
    exp = parse(text)
    assert isinstance(exp, Sat)
    assert exp.requires_optimization


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("% @expect sat\n% @model { a }\n", id="all-base-model"),
        pytest.param("% @expect sat\n% @cautious { a }\n", id="all-base-cautious"),
        pytest.param("% @expect sat\n% @brave { a }\n", id="all-base-brave"),
        pytest.param("% @expect sat\n% @count 2\n", id="all-base-count"),
        pytest.param("% @expect sat\n% @query yes { a }\n", id="query"),
        pytest.param("% @expect sat\n% @assign { v=1 }\n", id="assign"),
    ],
)
def test_requires_optimization_false_without_an_optimal_tag(text: str) -> None:
    exp = parse(text)
    assert isinstance(exp, Sat)
    assert not exp.requires_optimization


def test_requires_theory_true_iff_assign_present() -> None:
    with_assign = parse("% @expect sat\n% @assign { digit(s)=9 }\n")
    without = parse("% @expect sat\n% @model { a }\n")
    assert isinstance(with_assign, Sat)
    assert isinstance(without, Sat)
    assert with_assign.requires_theory
    assert not without.requires_theory


def test_two_assign_optimal_is_rejected() -> None:
    with pytest.raises(ContractError, match=r"@assign optimal"):
        parse("% @expect sat\n% @assign optimal { v=1 }\n% @assign optimal { w=2 }\n")


def test_unsat_excludes_assign_optimal() -> None:
    with pytest.raises(ContractError, match=r"unsat"):
        parse("% @expect unsat\n% @assign optimal { v=1 }\n")


def test_assign_and_assign_optimal_coexist() -> None:
    exp = parse("% @expect sat\n% @assign { v=1 }\n% @assign optimal { w=2 }\n")
    assert isinstance(exp, Sat | Unsat)


# --- the stranded `where` clause ---
# A `where { … }` clause qualifies a witness and must ride the litset's closing line. Written on a
# `%` line of its own it is absorbed by nothing, and the binding it carries would go with it —
# silently *weakening* the contract, since `requires_theory` goes too and the solver precondition
# that would have caught the case then does not fire either. A `%` line opening `where {` is
# therefore read as a clause wherever it stands and whatever tag came before it.

_STRANDED = [
    pytest.param("% @expect sat\n% @model { a }\n%   where { v=1 }\n", id="after-the-witness"),
    pytest.param(
        "% @expect sat\n% @model { a }\n% @note aside\n% where { v=1 }\n",
        id="after-an-intervening-note",
    ),
    pytest.param(
        "% @expect sat\n% @model { a }\n% @cautious { b }\n% where { v=1 }\n",
        id="after-another-tag",
    ),
    pytest.param("% @expect sat\n% where { v=1 }\n% @model { a }\n", id="before-the-witness"),
    pytest.param("% where { v=1 }\n% @expect sat\n% @model { a }\n", id="before-any-tag"),
    pytest.param(
        "% @expect sat\n% @model { a }\n% @note aside\n% where { v=1,\n%   w=2 }\n",
        id="brace-continued-onto-the-next-line",
    ),
    # The two that decided the rule's shape. A clause followed by anything at all is still a
    # clause, and reading further along the line to decide would let both of these through — a
    # binding dropped without a word, which is the one outcome the guard exists to prevent.
    pytest.param(
        "% @expect sat\n% @model { a }\n% where { v=1 }   % the theory binding\n",
        id="trailed-by-a-comment",
    ),
    pytest.param("% @expect sat\n% @model { a }\n% where { v=1 }.\n", id="trailed-by-a-full-stop"),
]


@pytest.mark.parametrize("text", _STRANDED)
def test_a_stranded_where_clause_is_refused_wherever_it_stands(text: str) -> None:
    with pytest.raises(ContractError, match=r"dangling `where`"):
        parse(text)


def test_the_stranded_where_diagnostic_names_the_file_and_the_line() -> None:
    # The guard fires anywhere in the file now, so the coordinate *is* the diagnostic: a reader can
    # no longer find the offending line by looking just under the witness. `match` is a search, so
    # asserting only the phrase leaves the whole provenance free.
    with pytest.raises(ContractError, match=r"^cases/x\.lp:4: dangling `where`"):
        parse(
            "% @expect sat\n% @model { a }\n% @note aside\n% where { v=1 }\n", source="cases/x.lp"
        )


def test_the_same_clauses_written_on_the_witness_line_parse_and_bind() -> None:
    # The companion to the table above, and it is what makes the table mean anything: each clause
    # refused there is well-formed, so what the refusal objects to is where it was written. Without
    # this the table would pass just as well over a parser that refused every `where` it ever met.
    single = parse("% @expect sat\n% @model { a } where { v=1 }\n% @note aside\n")
    assert isinstance(single, Sat)
    assert single.model is not None
    assert single.model.value.assign == frozenset({(parse_term("v"), 1)})
    assert single.requires_theory

    continued = parse("% @expect sat\n% @model { a } where { v=1,\n%   w=2 }\n")
    assert isinstance(continued, Sat)
    assert continued.model is not None
    assert continued.model.value.assign == frozenset({(parse_term("v"), 1), (parse_term("w"), 2)})


def test_empty_where_is_rejected() -> None:
    with pytest.raises(ContractError, match=r"where"):
        parse("% @expect sat\n% @model { a } where { }\n")


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            "% @expect sat\n% @model { a }\n% where the cost is low\n% @count 1\n",
            id="where-then-no-brace",
        ),
        pytest.param(
            "% @expect sat\n% @model { a }\n% the set where {x : p(x)} lives\n% @count 1\n",
            id="where-not-first-on-the-line",
        ),
        pytest.param(
            "% @expect sat\n% @model { a }\n% wherever { x } appears\n% @count 1\n",
            id="a-longer-word-beginning-where",
        ),
    ],
)
def test_prose_that_does_not_open_a_where_clause_stays_a_comment(text: str) -> None:
    # The whole of the acceptance side, and it is narrow on purpose: a comment is prose when it does
    # not *open* `where {`. The claim after it is read as usual, which is what shows the line was
    # passed over rather than swallowed into something.
    exp = parse(text)
    assert isinstance(exp, Sat)
    assert exp.count is not None
    assert exp.count.value == 1


def test_a_comment_opening_a_where_clause_is_refused_even_as_prose() -> None:
    # The cost of the rule, pinned rather than left to be discovered: set-builder notation written
    # at the start of a comment is refused, because it is indistinguishable from a stranded clause
    # and guessing between them is what lets a real binding through. Refusing a comment is a
    # refusal its author can answer by rewording; dropping a binding is a contract quietly
    # weakened. Neither corpus this project runs contains such a line.
    with pytest.raises(ContractError, match=r"dangling `where`"):
        parse("% @expect sat\n% @model { a }\n% where {x : p(x)} ranges over the grid\n")
