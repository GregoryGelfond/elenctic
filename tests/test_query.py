from typing import get_type_hints

import pytest
from clingo import Function, Number, String, Symbol, parse_term
from hypothesis import given
from hypothesis import strategies as st

from elenctic.determination import AnswerSet, Range, Truncation, WorldView
from elenctic.literals import Atoms, Literal
from elenctic.patterns import Pattern
from elenctic.query import (
    All,
    Answer,
    Answered,
    AnswerMode,
    Answers,
    Any,
    Bindings,
    Bound,
    Not,
    Query,
    ReadAnswers,
    Taken,
    Truth,
    answer,
    answered,
    answers,
    bindings,
    bodies,
    bravely,
    deciding,
    evaluate,
    instance_of,
    settled,
    stream,
)
from elenctic.terms import Compound, Term, Variable

P, Q, R = Literal("p"), Literal("q"), Literal("r")
X, Y = Variable("X"), Variable("Y")


def world(*members: set[Literal]) -> WorldView:
    return WorldView(frozenset(frozenset(m) for m in members))


literals = st.builds(Literal, st.sampled_from("pqr"), st.just(()), st.booleans())
consistent_sets = st.frozensets(literals, max_size=5).filter(
    lambda s: not any(lit.contrary in s for lit in s)
)
views = st.frozensets(consistent_sets, min_size=1, max_size=4).map(WorldView)
queries = st.recursive(
    literals,
    lambda inner: st.one_of(
        st.lists(inner, max_size=3).map(lambda parts: All(tuple(parts))),
        st.lists(inner, max_size=3).map(lambda parts: Any(tuple(parts))),
    ),
    max_leaves=6,
)


def test_a_literal_is_true_when_present_false_when_its_contrary_is_and_unknown_otherwise() -> None:
    member: Atoms = frozenset({P, Q.contrary})
    assert [evaluate(x, member) for x in (P, Q, R)] == [Truth.TRUE, Truth.FALSE, Truth.UNKNOWN]


def test_a_conjunction_is_as_true_as_its_least_true_part_and_a_disjunction_its_most() -> None:
    member: Atoms = frozenset({P, Q.contrary})
    assert evaluate(All((P, R)), member) is Truth.UNKNOWN
    assert evaluate(All((P, Q)), member) is Truth.FALSE
    assert evaluate(Any((R, Q)), member) is Truth.UNKNOWN
    assert evaluate(Any((P, Q)), member) is Truth.TRUE


def test_not_is_true_where_its_literal_is_absent_and_false_where_it_holds() -> None:
    member: Atoms = frozenset({P, Q.contrary})
    truths = [evaluate(Not(x), member) for x in (P, Q, R, Q.contrary)]
    assert truths == [Truth.FALSE, Truth.TRUE, Truth.TRUE, Truth.FALSE]


@given(consistent_sets, literals)
def test_not_is_never_unknown_in_an_answer_set(member: Atoms, literal: Literal) -> None:
    expected = Truth.FALSE if literal in member else Truth.TRUE
    assert evaluate(Not(literal), member) is expected


def test_a_conjunction_with_not_is_true_when_every_part_is_and_false_when_one_part_is() -> None:
    member: Atoms = frozenset({P})
    assert evaluate(All((P, Not(Q))), member) is Truth.TRUE
    assert evaluate(All((R, Not(P))), member) is Truth.FALSE
    assert evaluate(All((R, Not(Q))), member) is Truth.UNKNOWN


def test_not_of_a_literal_no_answer_set_holds_is_yes_though_the_literal_is_unknown() -> None:
    view = world({P}, {P, Q})
    assert answer(All((Not(R),)), view) is Answer.YES
    assert answer(R, view) is Answer.UNKNOWN


def test_not_of_a_literal_is_no_where_every_answer_set_holds_it_and_unknown_where_some_do() -> None:
    view = world({P}, {P, Q})
    assert answer(All((Not(P),)), view) is Answer.NO
    assert answer(All((Not(Q),)), view) is Answer.UNKNOWN


def test_a_ground_pattern_under_not_is_its_literal_under_not() -> None:
    member: Atoms = frozenset({Literal("p", (Number(1),))})
    assert evaluate(Not(Pattern("p", (Number(1),))), member) is Truth.FALSE
    with pytest.raises(ValueError, match="has variables"):
        evaluate(Not(Pattern("p", (X,))), member)


def test_the_empty_conjunction_is_true_and_the_empty_disjunction_false() -> None:
    assert evaluate(All(()), frozenset()) is Truth.TRUE
    assert evaluate(Any(()), frozenset()) is Truth.FALSE


def test_the_answer_is_yes_when_true_in_every_member_and_no_when_false_in_every_one() -> None:
    assert answer(All((P, Q)), world({P, Q}, {P, Q, R})) is Answer.YES
    assert answer(All((P, Q)), world({P.contrary}, {Q.contrary})) is Answer.NO
    assert answer(All((P, Q)), world({P, Q}, {P})) is Answer.UNKNOWN


def test_a_conjunction_false_in_each_member_for_a_different_reason_is_no() -> None:
    assert answer(All((P, Q)), world({P.contrary, Q}, {P, Q.contrary})) is Answer.NO


@given(consistent_sets, queries)
def test_negation_swaps_conjunction_and_disjunction(member: Atoms, query: Query) -> None:
    def dual(q: Query) -> Query:
        match q:
            case Literal() | Pattern():
                return q.contrary
            case All(parts):
                return Any(tuple(dual(p) for p in parts))
            case Any(parts):
                return All(tuple(dual(p) for p in parts))
            case Not():
                pytest.fail("`not` flips no truth to unknown, so it has no dual among queries")

    flipped = {Truth.TRUE: Truth.FALSE, Truth.FALSE: Truth.TRUE, Truth.UNKNOWN: Truth.UNKNOWN}
    assert evaluate(dual(query), member) is flipped[evaluate(query, member)]


def test_bindings_partition_the_instances_the_world_view_entertains() -> None:
    view = world(
        {Literal("p", (Number(1),)), Literal("p", (Number(2),), positive=False)},
        {
            Literal("p", (Number(1),)),
            Literal("p", (Number(2),), positive=False),
            Literal("p", (Number(3),)),
        },
    )
    assert bindings(Pattern("p", (X,)), view) == Bindings(
        yes=frozenset({(Number(1),)}),
        no=frozenset({(Number(2),)}),
        unknown=frozenset({(Number(3),)}),
    )


@given(views)
def test_yes_and_no_and_unknown_bindings_never_overlap(view: WorldView) -> None:
    found = bindings(Pattern("p", ()), view)
    assert not found.yes & found.no
    assert not found.yes & found.unknown
    assert not found.no & found.unknown


def sym(text: str) -> Symbol:
    return parse_term(text)


def lits(*texts: str) -> set[Literal]:
    return {Literal.parse(text) for text in texts}


NESTED = Pattern("p", (Compound("f", (X,)), sym("a")))


def test_a_nested_pattern_has_the_bindings_of_the_variables_beneath_its_function() -> None:
    view = world(
        lits("p(f(1),a)", "-p(f(2),a)", "p(f(9),b)", "p(g(5),a)"),
        lits("p(f(1),a)", "-p(f(2),a)", "p(f(3),a)", "p(f(9),b)"),
    )
    assert bindings(NESTED, view) == Bindings(
        yes=frozenset({(Number(1),)}),
        no=frozenset({(Number(2),)}),
        unknown=frozenset({(Number(3),)}),
    )


def test_a_pattern_that_repeats_a_variable_beneath_a_function_binds_it_once() -> None:
    twice = Pattern("p", (X, Compound("f", (X, Y))))
    view = world(lits("p(1,f(1,2))", "p(1,f(3,4))", "p(5,f(5,6))"))
    assert bindings(twice, view).yes == {(Number(1), Number(2)), (Number(5), Number(6))}


def test_bindings_keeps_its_pattern_parameter_and_takes_a_conjunction_too() -> None:
    """`bindings(pattern=…)` is 1.0's; since 1.1 the pattern may be a conjunction."""
    view = world(lits("p(1)", "q(1)"))
    assert bindings(pattern=Pattern("p", (X,)), view=view).yes == frozenset({(Number(1),)})
    both = All((Pattern("p", (X,)), Not(Pattern("q", (X,)))))
    assert bindings(both, world(lits("p(1)", "p(2)", "q(1)"))).yes == {(Number(2),)}
    assert get_type_hints(bindings)["pattern"] == Pattern | All


def test_a_conjunction_is_answered_over_the_world_view() -> None:
    both = All((Literal("p", (Number(1),)), Literal("q", (Number(1),))))
    assert answer(both, world(lits("p(1)", "q(1)"))) is Answer.YES
    assert answer(both, world(lits("p(1)"), lits("q(1)"))) is Answer.UNKNOWN


def test_a_ground_pattern_is_evaluated_as_the_literal_it_is() -> None:
    member = frozenset(lits("p(f(1))"))
    assert evaluate(Pattern("p", (sym("f(1)"),)), member) is Truth.TRUE
    assert evaluate(All((Pattern("p", (sym("f(2)"),)),)), member) is Truth.UNKNOWN


def test_a_pattern_with_variables_has_no_truth_in_an_answer_set_and_is_refused_not_false() -> None:
    with pytest.raises(ValueError, match="has bindings rather than an answer"):
        evaluate(NESTED, frozenset(lits("p(f(1),a)")))
    with pytest.raises(ValueError, match="has bindings rather than an answer"):
        answer(All((P, NESTED)), world(lits("p(f(1),a)")))


numbered = st.builds(
    Literal, st.just("p"), st.integers(1, 3).map(lambda n: (Number(n),)), st.booleans()
)
numbered_views = st.frozensets(
    st.frozensets(numbered, max_size=4).filter(lambda s: not any(x.contrary in s for x in s)),
    min_size=1,
    max_size=4,
).map(WorldView)


def _values(literals: Atoms, *, positive: bool) -> frozenset[tuple[Symbol, ...]]:
    return frozenset(x.arguments for x in literals if x.positive is positive)


@given(numbered_views)
def test_yes_and_no_bindings_are_the_unifiers_with_the_cautious_facts_and_their_contraries(
    view: WorldView,
) -> None:
    found = bindings(Pattern("p", (X,)), view)
    assert found.yes == _values(view.cautious, positive=True)
    assert found.no == _values(view.cautious, positive=False)


@given(numbered_views)
def test_unknown_bindings_are_the_brave_instances_neither_yes_nor_no(view: WorldView) -> None:
    found = bindings(Pattern("p", (X,)), view)
    entertained = _values(view.brave, positive=True) | _values(view.brave, positive=False)
    assert found.unknown == entertained - found.yes - found.no


@given(numbered_views)
def test_a_pattern_alone_has_yes_no_and_unknown_partitions(view: WorldView) -> None:
    found = bindings(Pattern("p", (X,)), view)
    assert found.yes.isdisjoint(found.no)
    assert found.yes.isdisjoint(found.unknown)
    assert found.no.isdisjoint(found.unknown)


@given(numbered_views, numbered)
def test_a_literal_is_yes_when_cautious_no_when_its_contrary_is_and_unknown_otherwise(
    view: WorldView, literal: Literal
) -> None:
    expected = (
        Answer.YES
        if literal in view.cautious
        else Answer.NO
        if literal.contrary in view.cautious
        else Answer.UNKNOWN
    )
    assert answer(literal, view) is expected
    assert answer(Pattern.of(literal), view) is expected
    per_member = {evaluate(All((literal,)), member) for member in view.members}
    assert (expected is Answer.YES) is (per_member == {Truth.TRUE})
    assert (expected is Answer.NO) is (per_member == {Truth.FALSE})


def test_a_literal_that_is_brave_but_not_cautious_is_unknown() -> None:
    p1 = Literal("p", (Number(1),))
    assert answer(p1, world({p1}, set())) is Answer.UNKNOWN
    assert bindings(Pattern("p", (X,)), world({p1}, set())).unknown == {(Number(1),)}


def test_a_tuple_pattern_binds_the_parts_of_a_tuple_and_nothing_else() -> None:
    pair = Pattern("p", (Compound("", (X, Y)),))
    view = world(lits("p((1,2))", "p(f(3,4))"))
    assert bindings(pair, view).yes == {(Number(1), Number(2))}


def test_a_compound_does_not_unify_with_a_symbol_that_is_not_a_function_of_its_shape() -> None:
    view = world({Literal("p", (sym("inf"),)), Literal("p", (sym("f"),)), *lits("p(f(1,2))")})
    assert bindings(Pattern("p", (Compound("f", (X,)),)), view) == Bindings(
        frozenset(), frozenset(), frozenset()
    )


def test_a_string_argument_with_separators_is_one_argument() -> None:
    view = world({Literal("p", (Number(1), String("a,b")))})
    assert bindings(Pattern("p", (X, String("a,b"))), view).yes == {(Number(1),)}


def test_a_pattern_with_an_anonymous_variable_is_refused_for_it_has_no_binding_to_give() -> None:
    with pytest.raises(ValueError, match="has an anonymous variable"):
        bindings(Pattern("p", (Variable("_"), X)), world(lits("p(1,2)", "p(f(1),2)", "q(2)")))


def test_a_repeated_variable_takes_one_value() -> None:
    view = world(lits("p(1,2)", "p(3,3)"))
    assert bindings(Pattern("p", (X, X)), view).yes == {(Number(3),)}


def test_a_pattern_nested_a_hundred_thousand_deep_has_bindings_without_recursion() -> None:
    pattern: Term = X
    ground: Symbol = Number(7)
    for _ in range(100_000):
        pattern = Compound("f", (pattern,))
        ground = Function("f", [ground])
    view = world({Literal("p", (ground,))})
    assert bindings(Pattern("p", (pattern,)), view).yes == {(Number(7),)}


def test_a_ground_literal_conjunction_is_answered_not_bound() -> None:
    both = All((Literal("p", (Number(1),)), Literal("q", (Number(1),))))
    assert answer(both, world(lits("p(1)", "q(1)", "q(2)"))) is Answer.YES


@pytest.mark.parametrize(
    ("members", "default", "cautious", "brave"),
    [
        ([{P}, {P, Q}], Answer.YES, Answer.YES, Answer.YES),
        ([{P.contrary}, {P.contrary, Q}], Answer.NO, Answer.NOT_ENTAILED, Answer.NONE_HOLDS),
        ([{P}, set()], Answer.UNKNOWN, Answer.NOT_ENTAILED, Answer.YES),
        ([set()], Answer.UNKNOWN, Answer.NOT_ENTAILED, Answer.NONE_HOLDS),
    ],
)
def test_each_mode_answers_from_the_same_per_member_truths(
    members: list[set[Literal]], default: Answer, cautious: Answer, brave: Answer
) -> None:
    view = world(*members)
    assert [answer(P, view, mode=mode) for mode in AnswerMode] == [default, cautious, brave]


@given(views, queries)
def test_cautious_and_brave_quantify_true_and_default_no_quantifies_false(
    view: WorldView, query: Query
) -> None:
    truths = [evaluate(query, member) for member in view.members]
    assert (answer(query, view, mode=AnswerMode.CAUTIOUS) is Answer.YES) is all(
        truth is Truth.TRUE for truth in truths
    )
    assert (answer(query, view, mode=AnswerMode.BRAVE) is Answer.YES) is any(
        truth is Truth.TRUE for truth in truths
    )
    assert (answer(query, view) is Answer.NO) is all(truth is Truth.FALSE for truth in truths)


def read(*members: set[Literal]) -> tuple[AnswerSet, ...]:
    return tuple(AnswerSet(frozenset(m), frozenset(m)) for m in members)


REACH = All((Pattern("r", (X,)), Not(Pattern("c", (X,)))))
ROADS = read(lits("r(a)", "r(b)", "c(b)"), lits("r(a)", "r(b)", "c(c)"))


def test_a_conjunction_with_variables_answers_each_binding_its_positive_parts_entertain() -> None:
    first, second = ROADS
    found = answers(REACH, ROADS)
    assert found == Answers(
        ("X",),
        (
            Bound((sym("a"),), Answer.YES, (Taken(Answer.YES, 1, first),)),
            Bound(
                (sym("b"),),
                Answer.UNKNOWN,
                (Taken(Answer.NO, 1, first), Taken(Answer.YES, 2, second)),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (AnswerMode.DEFAULT, [("a", Answer.YES), ("b", Answer.UNKNOWN)]),
        (AnswerMode.CAUTIOUS, [("a", Answer.YES), ("b", Answer.NOT_ENTAILED)]),
        (AnswerMode.BRAVE, [("a", Answer.YES), ("b", Answer.YES)]),
    ],
)
def test_each_binding_is_answered_as_the_mode_answers_its_instance(
    mode: AnswerMode, expected: list[tuple[str, Answer]]
) -> None:
    found = answers(REACH, ROADS, mode=mode)
    assert [(str(b.values[0]), b.answer) for b in found.bound] == expected


def test_bindings_are_shown_yes_first_then_as_their_mode_orders_answers_then_by_value() -> None:
    members = read(lits("p(3)", "p(1)", "-p(2)", "p(4)"), lits("p(3)", "p(1)", "-p(2)"))
    found = answers(Pattern("p", (X,)), members)
    assert [(b.values, b.answer) for b in found.bound] == [
        ((Number(1),), Answer.YES),
        ((Number(3),), Answer.YES),
        ((Number(2),), Answer.NO),
        ((Number(4),), Answer.UNKNOWN),
    ]
    assert [found.count(each) for each in (Answer.YES, Answer.NO, Answer.UNKNOWN)] == [2, 1, 1]


def test_bindings_of_one_answer_are_in_order_of_value_however_many_there_are() -> None:
    texts = [f"p({n})" for n in (17, 3, 29, 8, 41, 0, 12, 36, 5, 23, 2, 30, 11, 47, 19, 6)]
    texts += ['p("b")', "p(c)", 'p("a")', "p(f(1))", "p(a)"]
    found = answers(Pattern("p", (X,)), read(lits(*texts)))
    values = [b.values for b in found.bound]
    assert values == sorted(values)
    assert len(values) == len(texts)


def test_an_instance_needs_a_value_for_each_variable() -> None:
    with pytest.raises(ValueError, match="shorter"):
        instance_of(All((Pattern("p", (X, Y)),)), (Number(1),))


def test_a_binding_false_in_every_answer_set_is_no() -> None:
    members = read(lits("p(1)", "-q(1)"), lits("p(1)", "-q(1)", "q(2)"))
    found = answers(All((Pattern("p", (X,)), Pattern("q", (X,)))), members)
    assert [(b.values, b.answer) for b in found.bound] == [((Number(1),), Answer.NO)]


def test_parts_that_share_a_variable_join_on_it() -> None:
    members = read(lits("p(1)", "e(1,2)", "e(3,4)", "p(5)"))
    found = answers(All((Pattern("p", (X,)), Pattern("e", (X, Y)))), members)
    assert found.variables == ("X", "Y")
    assert found.giving(Answer.YES) == {(Number(1), Number(2))}
    assert len(found.bound) == 1


def test_a_ground_part_no_answer_set_entertains_leaves_no_binding_to_answer() -> None:
    members = read(lits("p(1)"))
    assert answers(All((Pattern("p", (X,)), Literal("zz"))), members).bound == ()
    found = answers(All((Pattern("p", (X,)), Not(Literal("zz")))), members)
    assert found.giving(Answer.YES) == {(Number(1),)}


@pytest.mark.parametrize(
    "query",
    [
        All((Not(Pattern("q", (X,))),)),
        All((Pattern("p", (X,)), Not(Pattern("q", (X, Y))))),
    ],
)
def test_a_variable_only_under_not_is_unsafe_and_refused(query: Query) -> None:
    with pytest.raises(ValueError, match="only under `not`"):
        answers(query, read(lits("p(1)")))


def test_a_disjunction_with_variables_has_no_bindings_to_give() -> None:
    with pytest.raises(ValueError, match="disjunction"):
        answers(Any((Pattern("p", (X,)), P)), read(lits("p(1)")))


def test_bindings_over_a_world_view_group_the_answers_of_its_members() -> None:
    view = world(lits("r(a)", "r(b)", "c(b)"), lits("r(a)", "r(b)", "c(c)"))
    assert bindings(REACH, view) == Bindings(
        frozenset({(sym("a"),)}), frozenset(), frozenset({(sym("b"),)})
    )


@given(numbered_views)
def test_a_pattern_alone_by_default_is_answered_as_its_unifiers_with_the_consequences(
    view: WorldView,
) -> None:
    pattern = Pattern("p", (X,))
    cautious, brave = view.cautious, view.brave
    yes = {lit.arguments for lit in cautious if lit.positive}
    no = {lit.arguments for lit in cautious if not lit.positive}
    entertained = {lit.arguments for lit in brave}
    found = answers(pattern, tuple(AnswerSet(m, m) for m in view.members))
    assert found.giving(Answer.YES) == yes
    assert found.giving(Answer.NO) == no
    assert found.giving(Answer.UNKNOWN) == entertained - yes - no


def test_the_stream_shows_yes_then_no_bindings_and_unknown_ones_only_on_request() -> None:
    members = read(lits("p(3)", "p(1)", "-p(2)", "p(4)"), lits("p(3)", "p(1)", "-p(2)"))
    found = answered(Pattern("p", (X,)), members)
    assert [(b.values, b.answer) for b in stream(found)] == [
        ((Number(1),), Answer.YES),
        ((Number(3),), Answer.YES),
        ((Number(2),), Answer.NO),
    ]
    assert [b.values for b in stream(found, unknown=True)][-1] == (Number(4),)


@pytest.mark.parametrize("mode", [AnswerMode.CAUTIOUS, AnswerMode.BRAVE])
def test_the_stream_of_a_cautious_or_brave_query_shows_only_its_yes_bindings(
    mode: AnswerMode,
) -> None:
    found = answered(REACH, ROADS, mode=mode)
    assert {b.answer for b in stream(found, unknown=True)} == {Answer.YES}


def test_the_stream_of_a_ground_query_is_its_one_answer_with_no_values() -> None:
    found = answered(All((Literal("r", (sym("a"),)),)), ROADS)
    assert list(stream(found)) == [Bound((), Answer.YES, found.taken)]


def test_a_brave_search_cut_keeps_the_yes_bindings_it_found_and_says_what_cut_it() -> None:
    first, _ = ROADS
    found = bravely(REACH, (first,), Range.ALL, Truncation.MAX_ANSWER_SETS)
    assert isinstance(found, Answered)
    assert isinstance(found.answer, Answers)
    assert [b.values for b in found.answer.bound] == [(sym("a"),)]
    assert (found.read, found.cut, found.mode) == (
        None,
        Truncation.MAX_ANSWER_SETS,
        AnswerMode.BRAVE,
    )


def test_a_brave_search_cut_before_any_yes_has_nothing_to_show() -> None:
    nothing = read(lits("c(a)"))
    assert bravely(REACH, nothing, Range.ALL, Truncation.MAX_ANSWER_SETS) is None
    assert bravely(All((Literal("zz"),)), nothing, Range.ALL, Truncation.MAX_SECONDS) is None
    ground = bravely(All((Literal("c", (sym("a"),)),)), nothing, Range.ALL, Truncation.MAX_SECONDS)
    assert ground is not None
    assert (ground.answer, ground.cut) == (Answer.YES, Truncation.MAX_SECONDS)


@pytest.mark.parametrize(
    ("query", "true", "false"),
    [
        (P, (("p",),), (("-p",),)),
        (Not(P), (("not p",),), (("p",),)),
        (All((P, Not(Q))), (("p", "not q"),), (("-p",), ("q",))),
        (Any((P, Not(Q))), (("p",), ("not q",)), (("-p", "q"),)),
        (All(()), ((),), ()),
        (Any(()), (), ((),)),
        (Pattern("p", ()), (("p",),), (("-p",),)),
        (Not(Pattern("p", ())), (("not p",),), (("p",),)),
    ],
)
def test_rule_bodies_hold_exactly_where_the_query_is_true_or_false(
    query: Query, true: tuple[tuple[str, ...], ...], false: tuple[tuple[str, ...], ...]
) -> None:
    assert bodies(query, Truth.TRUE) == true
    assert bodies(query, Truth.FALSE) == false


def test_rule_bodies_need_a_ground_query_and_a_true_or_false_truth() -> None:
    with pytest.raises(ValueError, match="variables"):
        bodies(Pattern("p", (X,)), Truth.TRUE)
    with pytest.raises(ValueError, match="neither true nor false"):
        bodies(P, Truth.UNKNOWN)


def test_a_brave_answer_names_only_the_answer_sets_where_the_query_is_true() -> None:
    members = read(lits(), lits("p"), lits("-p"))
    bravely = answered(All((P,)), members, mode=AnswerMode.BRAVE)
    assert [(each.answer, each.index) for each in bravely.taken] == [(Answer.YES, 2)]
    by_default = answered(All((P,)), members)
    assert [each.answer for each in by_default.taken] == [Answer.UNKNOWN, Answer.YES, Answer.NO]
    none = answered(All((P,)), read(lits("-p"), lits()), mode=AnswerMode.BRAVE)
    assert (none.answer, none.taken) == (Answer.NONE_HOLDS, ())


def test_a_brave_binding_names_only_the_answer_sets_where_it_is_true() -> None:
    members = read(lits("-p(1)"), lits("p(1)", "-p(2)"))
    found = answers(Pattern("p", (X,)), members, mode=AnswerMode.BRAVE)
    assert [(b.values, [t.index for t in b.taken]) for b in found.bound] == [((Number(1),), [2])]


def test_a_brave_answer_cut_short_names_only_where_it_is_true_past_what_was_read() -> None:
    reading = ReadAnswers(read(lits()), Truncation.MAX_ANSWER_SETS, None)
    found = settled(All((P,)), reading, {Truth.TRUE, Truth.UNKNOWN}, AnswerMode.BRAVE)
    assert (found.answer, found.taken) == (Answer.YES, ())
    assert [each.answer for each in found.unreached] == [Answer.YES]


def test_a_query_rests_on_the_literal_of_each_part_that_holds_or_on_both_where_neither_does() -> (
    None
):
    a, b, c = Literal("a"), Literal("b"), Literal("c")
    member = frozenset({a, b.contrary})
    query = All((a, b, Not(c), Any((c,))))
    assert deciding(query, member) == (a, b.contrary, c, c, c.contrary)
