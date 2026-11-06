import pytest
from clingo import Function, Number, String, Symbol, parse_term
from hypothesis import given
from hypothesis import strategies as st

from elenctic.determination import WorldView
from elenctic.literals import Atoms, Literal
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


def test_bindings_takes_a_pattern_not_a_compound_query() -> None:
    """Compound queries are answered by `answer`; `bindings` is for one pattern (1.0)."""
    view = world(lits("p(1)", "q(1)"))
    assert bindings(Pattern("p", (X,)), view).yes == frozenset({(Number(1),)})
    with pytest.raises(AttributeError):
        bindings(All((Pattern("p", (X,)), Pattern("q", (X,)))), view)  # type: ignore[arg-type]


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
