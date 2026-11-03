import pytest
from clingo import Number, Symbol, parse_term
from hypothesis import given
from hypothesis import strategies as st

from elenctic.determination import WorldView
from elenctic.extension import Extension
from elenctic.literals import AnswerSet, Literal
from elenctic.patterns import Pattern
from elenctic.query import (
    All,
    Answer,
    Any,
    Bindings,
    Query,
    Truth,
    answer,
    bindings,
    evaluate,
)
from elenctic.terms import Compound, Variable

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
    member: AnswerSet = frozenset({P, Q.contrary})
    assert [evaluate(x, member) for x in (P, Q, R)] == [Truth.TRUE, Truth.FALSE, Truth.UNKNOWN]


def test_a_conjunction_is_as_true_as_its_least_true_part_and_a_disjunction_its_most() -> None:
    member: AnswerSet = frozenset({P, Q.contrary})
    assert evaluate(All((P, R)), member) is Truth.UNKNOWN
    assert evaluate(All((P, Q)), member) is Truth.FALSE
    assert evaluate(Any((R, Q)), member) is Truth.UNKNOWN
    assert evaluate(Any((P, Q)), member) is Truth.TRUE


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
def test_negation_swaps_conjunction_and_disjunction(member: AnswerSet, query: Query) -> None:
    def dual(q: Query) -> Query:
        match q:
            case Literal() | Pattern():
                return q.contrary
            case All(parts):
                return Any(tuple(dual(p) for p in parts))
            case Any(parts):
                return All(tuple(dual(p) for p in parts))

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


def test_a_conjunction_of_patterns_joins_their_bindings_on_the_variables_they_share() -> None:
    both = All((Pattern("p", (X,)), Pattern("q", (X, Y))))
    view = world(lits("p(1)", "p(2)", "q(1,a)", "q(3,b)", "-q(2,c)"))
    assert bindings(both, view) == Bindings(
        yes=frozenset({(Number(1), sym("a"))}),
        no=frozenset({(Number(2), sym("c"))}),
        unknown=frozenset(),
    )


def test_an_instance_is_as_true_as_the_least_true_part_of_a_conjunction() -> None:
    both = All((Pattern("p", (X,)), Pattern("q", (X,))))
    view = world(
        lits("p(1)", "q(1)", "p(2)", "p(3)", "-q(3)"),
        lits("p(1)", "q(1)", "p(2)", "p(3)", "-q(3)", "q(2)"),
    )
    found = bindings(both, view)
    assert (found.yes, found.no, found.unknown) == (
        frozenset({(Number(1),)}),
        frozenset({(Number(3),)}),
        frozenset({(Number(2),)}),
    )


def test_a_disjunction_of_patterns_over_the_same_variables_unites_their_bindings() -> None:
    either = Any((Pattern("p", (X,)), Pattern("q", (X,))))
    view = world(lits("p(1)", "q(2)", "-q(1)"))
    assert bindings(either, view) == Bindings(
        yes=frozenset({(Number(1),), (Number(2),)}), no=frozenset(), unknown=frozenset()
    )


def test_a_disjunction_over_different_variables_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot unite"):
        bindings(Any((Pattern("p", (X,)), Pattern("q", (Y,)))), world(lits("p(1)", "q(1)")))


def test_an_empty_disjunction_entertains_nothing_and_an_empty_conjunction_one_instance() -> None:
    view = world(lits("p"))
    assert bindings(Any(()), view) == Bindings(frozenset(), frozenset(), frozenset())
    assert bindings(All(()), view).yes == {()}


def test_a_ground_pattern_is_evaluated_as_the_literal_it_is() -> None:
    member = frozenset(lits("p(f(1))"))
    assert evaluate(Pattern("p", (sym("f(1)"),)), member) is Truth.TRUE
    assert evaluate(All((Pattern("p", (sym("f(2)"),)),)), member) is Truth.UNKNOWN


def test_a_pattern_with_variables_has_no_truth_in_an_answer_set_and_is_refused_not_false() -> None:
    with pytest.raises(ValueError, match="has bindings rather than an answer"):
        evaluate(NESTED, frozenset(lits("p(f(1),a)")))
    with pytest.raises(ValueError, match="has bindings rather than an answer"):
        answer(All((P, NESTED)), world(lits("p(f(1),a)")))


@given(views)
def test_the_bindings_of_a_pattern_are_the_ones_its_literals_and_their_contraries_give(
    view: WorldView,
) -> None:
    pattern = Pattern("p", ())
    cautious, brave = Extension(view.cautious), Extension(view.brave)
    yes = pattern.bindings_in(cautious)
    no = pattern.contrary.bindings_in(cautious)
    entertained = pattern.bindings_in(brave) | pattern.contrary.bindings_in(brave)
    assert bindings(pattern, view) == Bindings(yes, no, entertained - yes - no)


def test_a_ground_part_of_a_conjunction_joins_the_bindings_of_the_others_without_binding() -> None:
    both = All((Literal("p", (Number(1),)), Pattern("q", (X,))))
    view = world(lits("p(1)", "q(1)", "q(2)", "-q(3)"))
    assert bindings(both, view) == Bindings(
        yes=frozenset({(Number(1),), (Number(2),)}),
        no=frozenset({(Number(3),)}),
        unknown=frozenset(),
    )
