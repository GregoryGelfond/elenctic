"""``expectation.parse`` — the positive cases: every tag parses to the right cell of
the ``Expectation`` sum, continuation lines join an unclosed litset (and *only* that),
and a source label threads file:line provenance into diagnostics (spec §2.1)."""

from clingo import Symbol, parse_term

from elenctic.expectation import Sat, Unsat, WitnessClaim, parse
from elenctic.query import Answer, GroundQuery


def L(*names: str) -> frozenset[Symbol]:
    """A litset built from clingo ground terms — the structural-equality currency (spec §2.0)."""
    return frozenset(parse_term(name) for name in names)


def WL(*names: str) -> WitnessClaim:
    """A WitnessClaim built from a litset (a bare, empty-assign witness)."""
    return WitnessClaim(shown=L(*names))


def test_parse_expect_unsat_with_note() -> None:
    exp = parse("% @expect unsat\n% @note the budget cap excludes every s-t path\n")
    assert isinstance(exp, Unsat)
    assert exp.notes == ("the budget cap excludes every s-t path",)


def test_parse_expect_sat_minimal_model() -> None:
    exp = parse("% @expect sat\n% @model { a }\n")
    assert isinstance(exp, Sat)
    assert exp.model == WL("a")
    assert exp.optimal_model is None


def test_bare_witness_carries_an_empty_assignment() -> None:
    # A bare @model parses to a WitnessClaim with no joint binding — the where-clause (later) fills
    # the assign; until then assign is empty, so has_model reads the shown census, not the full one.
    exp = parse("% @expect sat\n% @model { a, b }\n")
    assert isinstance(exp, Sat)
    assert exp.model == WitnessClaim(shown=L("a", "b"))
    assert exp.model is not None and exp.model.assign == frozenset()


def test_parse_sat_with_cost_and_optimal_witness() -> None:
    exp = parse(
        "% @expect  sat\n"
        "% @cost    { 4 2 }\n"
        "% @optimal { included(s,a,2,1), included(a,t,2,1), start(s), end(t) }\n"
    )
    assert isinstance(exp, Sat)
    assert exp.cost == (4, 2)
    assert exp.optimal_model == WL("included(s,a,2,1)", "included(a,t,2,1)", "start(s)", "end(t)")
    assert exp.model is None


def test_cost_single_component() -> None:
    exp = parse("% @expect sat\n% @cost { 8 }\n")
    assert isinstance(exp, Sat)
    assert exp.cost == (8,)


def test_cautious_accumulates_at_base() -> None:
    exp = parse("% @expect sat\n% @cautious { start(s) }\n% @cautious { end(t) }\n")
    assert isinstance(exp, Sat)
    assert exp.cautious == L("start(s)", "end(t)")  # union of the two claims
    assert exp.cautious_optimal == frozenset()


def test_cautious_optimal_is_a_distinct_cell_from_cautious() -> None:
    exp = parse("% @expect sat\n% @cautious { p }\n% @cautious optimal { q }\n")
    assert isinstance(exp, Sat)
    assert exp.cautious == L("p")
    assert exp.cautious_optimal == L("q")


def test_brave_accumulates_and_brave_optimal_is_distinct() -> None:
    exp = parse("% @expect sat\n% @brave { a }\n% @brave { b }\n% @brave optimal { c }\n")
    assert isinstance(exp, Sat)
    assert exp.brave == L("a", "b")
    assert exp.brave_optimal == L("c")


def test_count_base_axis() -> None:
    exp = parse("% @expect sat\n% @count 3\n% @count optimal 2\n")
    assert isinstance(exp, Sat)
    assert exp.count == 3
    assert exp.count_optimal == 2


def test_parse_assign_bindings() -> None:
    exp = parse("% @expect sat\n% @assign { digit(s)=9, digit(e)=5 }\n")
    assert isinstance(exp, Sat)
    assert exp.assign == frozenset({(parse_term("digit(s)"), 9), (parse_term("digit(e)"), 5)})


def test_assign_accepts_a_negative_value() -> None:
    exp = parse("% @expect sat\n% @assign { offset(x)=-3 }\n")
    assert isinstance(exp, Sat)
    assert exp.assign == frozenset({(parse_term("offset(x)"), -3)})


def test_model_optimal_populates_the_optimal_cell() -> None:
    exp = parse("% @expect sat\n% @model optimal { a, b }\n")
    assert isinstance(exp, Sat)
    assert exp.optimal_model == WL("a", "b")
    assert exp.model is None


def test_optimal_is_sugar_for_model_optimal_and_coexists_with_model() -> None:
    # @optimal ≡ @model optimal (spec §2.1); the all-base @model is a distinct cell (§2.2 rule 2).
    exp = parse("% @expect sat\n% @model { a }\n% @optimal { b }\n")
    assert isinstance(exp, Sat)
    assert exp.model == WL("a")
    assert exp.optimal_model == WL("b")


def test_litset_accepts_strong_negation_literal() -> None:
    exp = parse("% @expect sat\n% @cautious { -reachable(x) }\n")
    assert isinstance(exp, Sat)
    assert exp.cautious == L("-reachable(x)")


def test_litset_is_paren_aware() -> None:
    exp = parse("% @expect sat\n% @model { included(s,a,2,1), start(s) }\n")
    assert isinstance(exp, Sat)
    assert exp.model == WL("included(s,a,2,1)", "start(s)")


def test_queries_are_collected_in_order() -> None:
    exp = parse("% @expect sat\n% @query yes { start(s), end(t) }\n% @query no { reachable(x) }\n")
    assert isinstance(exp, Sat)
    assert len(exp.queries) == 2
    assert all(isinstance(q, GroundQuery) for q in exp.queries)
    assert exp.queries[0].answer is Answer.yes
    assert exp.queries[1].answer is Answer.no


def test_binding_query_is_collected() -> None:
    exp = parse("% @expect sat\n% @query yes { reachable(X) } = { s, a, t }\n")
    assert isinstance(exp, Sat)
    assert len(exp.queries) == 1


def test_notes_accumulate() -> None:
    exp = parse("% @expect sat\n% @model { a }\n% @note first\n% @note second\n")
    assert isinstance(exp, Sat)
    assert exp.notes == ("first", "second")


def test_continuation_joins_an_unclosed_litset() -> None:
    exp = parse("% @expect sat\n% @model { assign(s,9),\n%          assign(e,5) }\n")
    assert isinstance(exp, Sat)
    assert exp.model == WL("assign(s,9)", "assign(e,5)")


def test_continuation_does_not_absorb_prose_after_a_closed_litset() -> None:
    # dx#1 / spec §2.1: a continuation absorbs only the unfinished litset, never a later
    # prose '%' line (e.g. a '% Run: …' header). Were the prose absorbed, @model's payload
    # would not end in '}' and _base_litset would reject it.
    exp = parse(
        "% @expect sat\n"
        "% @model { included(s,a,2,1),\n"
        "%          start(s) }\n"
        "% Run: clingo shortest-path.lp variant-03.lp\n"
    )
    assert isinstance(exp, Sat)
    assert exp.model == WL("included(s,a,2,1)", "start(s)")


def test_prose_comment_between_tags_is_ignored() -> None:
    exp = parse("% @expect sat\n% @cautious { a }\n% just a stray remark\n% @brave { b }\n")
    assert isinstance(exp, Sat)
    assert exp.cautious == L("a")
    assert exp.brave == L("b")


def test_ignores_non_contract_comments_and_program_code() -> None:
    exp = parse("% a real comment\nfoo :- bar.\n% @expect sat\n% @model { a }\n")
    assert isinstance(exp, Sat)
    assert exp.model == WL("a")


def test_parse_accepts_a_source_label() -> None:
    # dx#2: a source label is accepted (and threaded into diagnostics — see the well-formed suite).
    exp = parse("% @expect sat\n% @model { a }\n", source="cases/x.lp")
    assert isinstance(exp, Sat)
    assert exp.model == WL("a")


def test_continuation_spans_three_lines() -> None:
    exp = parse("% @expect sat\n% @model { a,\n%          b,\n%          c }\n")
    assert isinstance(exp, Sat)
    assert exp.model == WL("a", "b", "c")


def test_cautious_optimal_accumulates() -> None:
    exp = parse("% @expect sat\n% @cautious optimal { a }\n% @cautious optimal { b }\n")
    assert isinstance(exp, Sat)
    assert exp.cautious_optimal == L("a", "b")


def test_tag_order_is_irrelevant() -> None:
    # The builder is order-independent: @expect may appear last (a contract is a set of claims).
    exp = parse("% @model { a }\n% @count 1\n% @expect sat\n")
    assert isinstance(exp, Sat)
    assert exp.model == WL("a")
    assert exp.count == 1


def test_assign_term_with_internal_comma_is_one_binding() -> None:
    # _split_top is paren-aware: a comma inside f(a,b) is not a binding separator.
    exp = parse("% @expect sat\n% @assign { f(a,b)=1 }\n")
    assert isinstance(exp, Sat)
    assert exp.assign == frozenset({(parse_term("f(a,b)"), 1)})


def test_cost_accepts_a_negative_component() -> None:
    # A cost component is a clingo integer (a #minimize weight may be negative); §2.0 reads the
    # natural objective value. The regex accepts -?\d+ deliberately (beyond the plan's \d+ sketch).
    exp = parse("% @expect sat\n% @cost { -4 2 }\n")
    assert isinstance(exp, Sat)
    assert exp.cost == (-4, 2)


def test_note_with_brace_does_not_absorb_a_following_prose_line() -> None:
    # A @note is free prose to end of line (spec §2.1 EBNF), not a litset: a stray '{' in note
    # prose must NOT turn the following '%' line into a continuation. Only litset-bearing tags
    # span continuations.
    exp = parse(
        "% @expect sat\n% @note uses a { to mark a choice\n% Run: clingo foo.lp\n% @model { a }\n"
    )
    assert isinstance(exp, Sat)
    assert exp.notes == ("uses a { to mark a choice",)
    assert exp.model == WL("a")
