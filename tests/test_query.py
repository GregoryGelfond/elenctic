from clingo import Number
from hypothesis import given
from hypothesis import strategies as st

from elenctic.determination import WorldView
from elenctic.literals import AnswerSet, Literal, Pattern, Variable
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
    singleton_answer,
)

P, Q, R = Literal("p"), Literal("q"), Literal("r")
X = Variable("X")


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


@given(views, literals)
def test_a_single_literal_is_settled_by_the_cautious_consequences_alone(
    view: WorldView, literal: Literal
) -> None:
    assert singleton_answer(literal, view.cautious) is answer(literal, view)


@given(consistent_sets, queries)
def test_negation_swaps_conjunction_and_disjunction(member: AnswerSet, query: Query) -> None:
    def dual(q: Query) -> Query:
        match q:
            case Literal():
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
