import itertools
from time import perf_counter

import pytest
from clingo import Function, Number, Symbol, parse_term
from hypothesis import given, settings
from hypothesis import strategies as st

from elenctic.patterns import Pattern
from elenctic.substitution import Substitution
from elenctic.terms import Compound, Term, Variable, build, rename, variables
from elenctic.unify import Fresh, mgu, rename_apart, unify, unify_terms
from reference import alpha_equivalent, reference_instance

X, Y, Z = Variable("X"), Variable("Y"), Variable("Z")
A, B = parse_term("a"), parse_term("b")


def f(*arguments: Term, positive: bool = True) -> Term:
    return build("f", arguments, positive=positive)


def instance(left: Term, right: Term) -> Term | None:
    """Return what `left` becomes under the unifier of `left` and `right`, if they unify."""
    found = unify_terms([left], [right])
    return None if found is None else found.apply(left)


def test_a_variable_unifies_with_any_term() -> None:
    assert instance(X, f(A)) == f(A)
    assert instance(f(A), X) == f(A)


def test_the_same_variable_unifies_with_itself_and_binds_nothing() -> None:
    assert unify_terms([X], [X]) == Substitution()


def test_two_variables_unify_by_the_lesser_standing_for_both() -> None:
    found = unify_terms([X], [Y])
    assert found == Substitution({Y: X})


def test_distinct_atoms_do_not_unify_and_equal_ones_do() -> None:
    assert unify_terms([A], [B]) is None
    assert unify_terms([A], [A]) == Substitution()
    assert unify_terms([Number(1)], [Number(2)]) is None
    assert unify_terms([Number(1)], [parse_term('"1"')]) is None


def test_functions_unify_argument_by_argument() -> None:
    found = unify_terms([f(X, B)], [f(A, Y)])
    assert found is not None
    assert found.apply(X) == A
    assert found.apply(Y) == B


def test_functions_of_different_functor_arity_or_sign_do_not_unify() -> None:
    assert unify_terms([f(X)], [build("g", [X])]) is None
    assert unify_terms([f(X)], [f(X, Y)]) is None
    assert unify_terms([f(X)], [f(X, positive=False)]) is None
    assert unify_terms([f(X)], [A]) is None


def test_a_function_never_unifies_with_a_number() -> None:
    assert unify_terms([f(X)], [Number(1)]) is None


def test_a_variable_cannot_be_a_term_that_contains_it() -> None:
    assert unify_terms([X], [f(X)]) is None
    assert unify_terms([f(X, Y)], [f(Y, f(X))]) is None


def test_a_cycle_through_several_bindings_is_found_once_at_the_end() -> None:
    assert unify_terms([X, Y, Z], [f(Y), f(Z), f(X)]) is None


def test_a_variable_repeated_forces_its_two_places_to_agree() -> None:
    assert unify_terms([f(X, X)], [f(A, B)]) is None
    assert instance(f(X, X), f(A, Y)) == f(A, A)


def test_the_unifier_is_triangular_but_applies_fully() -> None:
    found = unify_terms([X, Y], [f(Y), A])
    assert found is not None
    assert found.get(X) == f(Y)
    assert found.apply(X) == f(A)


def test_each_anonymous_variable_is_its_own() -> None:
    anonymous = Variable("_")
    found = unify_terms([f(anonymous, anonymous)], [f(A, B)])
    assert found is not None
    assert found.apply(f(A, B)) == f(A, B)


def test_a_ground_function_unifies_by_walking_its_symbol() -> None:
    assert instance(f(X), parse_term("f(g(1))")) == parse_term("f(g(1))")
    assert unify_terms([f(X)], [parse_term("g(1)")]) is None


def test_two_terms_sharing_one_large_ground_part_unify_in_one_walk() -> None:
    shared = parse_term("f(g(h(1),h(2)),g(h(1),h(2)))")
    assert unify_terms([Compound("k", (X, shared))], [Compound("k", (shared, X))]) is not None


def test_a_number_of_terms_unify_pairwise_with_one_unifier() -> None:
    found = unify_terms([X, Y], [Y, A])
    assert found is not None
    assert (found.apply(X), found.apply(Y)) == (A, A)


def test_two_sequences_of_different_length_cannot_be_unified_by_position() -> None:
    with pytest.raises(ValueError, match="argument"):
        unify_terms([X], [X, Y])


def test_patterns_of_different_signatures_do_not_unify() -> None:
    assert unify(Pattern("p", (X,)), Pattern("q", (X,))) is None
    assert unify(Pattern("p", (X,)), Pattern("p", (X,), positive=False)) is None
    assert unify(Pattern("p", (X,)), Pattern("p", (X, Y))) is None


def test_the_most_general_unifier_renames_the_two_patterns_apart() -> None:
    found = mgu(Pattern("p", (X, f(Y))), Pattern("p", (f(X), Y)))
    assert found is not None
    assert [alpha_equivalent(a, f(Variable("v"))) for a in found.instance.arguments] == [True, True]
    assert str(found.first) != str(found.second)


def test_a_variable_of_one_pattern_is_not_a_variable_of_the_other_for_its_name() -> None:
    assert mgu(Pattern("p", (X, X)), Pattern("p", (A, B))) is None
    assert mgu(Pattern("p", (X, A)), Pattern("p", (B, X))) is not None


def test_two_patterns_that_do_not_unify_have_no_unifier() -> None:
    assert mgu(Pattern("p", (A,)), Pattern("p", (B,))) is None


def test_fresh_variables_avoid_those_in_use() -> None:
    fresh = Fresh([Variable("_G0"), Variable("_G2")])
    assert [fresh.variable().name for _ in range(3)] == ["_G1", "_G3", "_G4"]


def test_renaming_apart_is_consistent_and_makes_each_anonymous_variable_new() -> None:
    renamed = rename_apart(Pattern("p", (X, f(X), Variable("_"), Variable("_"))), Fresh())
    first, second, third, fourth = renamed.arguments
    assert isinstance(first, Variable)
    assert second == f(first)
    assert isinstance(third, Variable)
    assert third != fourth


# Deep nesting, where recursion would fail ------------------------------------------------------


def chain(depth: int, last: Term) -> Term:
    term = last
    for _ in range(depth):
        term = f(term)
    return term


DEPTH = 100_000


def test_terms_nested_a_hundred_thousand_deep_unify_without_recursion() -> None:
    found = unify_terms([chain(DEPTH, X)], [chain(DEPTH, A)])
    assert found is not None
    assert found.get(X) == A


def test_a_variable_bound_to_a_very_deep_term_is_written_out_by_apply() -> None:
    found = unify_terms([X], [chain(DEPTH, A)])
    assert found is not None
    assert found.apply(X) == chain(DEPTH, A)


def test_the_occurs_check_finds_a_cycle_a_hundred_thousand_deep() -> None:
    assert unify_terms([X], [chain(DEPTH, X)]) is None


def test_two_very_deep_terms_that_differ_at_the_bottom_do_not_unify() -> None:
    assert unify_terms([chain(DEPTH, A)], [chain(DEPTH, B)]) is None


def test_a_very_deep_ground_symbol_is_taken_apart_and_unified() -> None:
    deep: Symbol = Number(0)
    for _ in range(DEPTH):
        deep = Function("f", [deep])
    found = unify_terms([chain(DEPTH, X)], [deep])
    assert found is not None
    assert found.get(X) == Number(0)


def exponential(size: int) -> tuple[list[Term], list[Term]]:
    """Build `Xi = g(Xi+1, Xi+1)` and `X(last) = a`: a solution of exponential size."""
    xs = [Variable(f"X{i}") for i in range(size)]
    return [*xs], [*(build("g", [x, x]) for x in xs[1:]), A]


def seconds_to_unify(size: int) -> float:
    left, right = exponential(size)
    started = perf_counter()
    assert unify_terms(left, right) is not None
    return perf_counter() - started


def test_a_solution_of_exponential_size_is_found_and_read_out_in_linear_time() -> None:
    left, right = exponential(3)
    found = unify_terms(left, right)
    assert found is not None
    assert found.get(Variable("X0")) == Compound("g", (Variable("X1"), Variable("X1")))
    assert found.apply(Variable("X0")) == parse_term("g(g(a,a),g(a,a))")


def test_unifying_eight_times_as_much_takes_about_eight_times_as_long_not_sixty_four() -> None:
    small = min(seconds_to_unify(2_000) for _ in range(3))
    large = min(seconds_to_unify(16_000) for _ in range(3))
    assert large < 24 * small


# Properties, against a naive reference -----------------------------------------------------------

NAMES = [Variable(name) for name in ("X", "Y", "Z", "W")]
LEAVES = st.one_of(
    st.sampled_from([A, B, Number(1), parse_term('"s"')]),
    st.sampled_from(NAMES),
    st.just(Variable("_")),
)


def extend(below: st.SearchStrategy[Term]) -> st.SearchStrategy[Term]:
    functor = st.sampled_from([("f", True), ("g", True), ("f", False), ("", True)])
    return st.builds(
        lambda head, arguments: build(head[0], arguments, positive=head[1]),
        functor,
        st.lists(below, min_size=1, max_size=3),
    )


TERMS = st.recursive(LEAVES, extend, max_leaves=10)


def apart(term: Term, tag: str, counter: itertools.count[int]) -> Term:
    """Give each anonymous variable of `term` a name of its own, as the reference needs."""
    return rename(
        term,
        lambda v: Variable(f"{tag}{next(counter)}") if v.anonymous else v,
    )


def undisturbed(left: Term, right: Term) -> tuple[Term, Term]:
    counter = itertools.count()
    return apart(left, "_L", counter), apart(right, "_R", counter)


@settings(max_examples=400, deadline=None)
@given(TERMS, TERMS)
def test_unifiability_and_the_common_instance_agree_with_the_reference(
    left: Term, right: Term
) -> None:
    separate_left, separate_right = undisturbed(left, right)
    expected = reference_instance(separate_left, separate_right)
    found = unify_terms([separate_left], [separate_right])
    assert (found is None) is (expected is None)
    assert (unify_terms([left], [right]) is None) is (expected is None)
    if found is not None and expected is not None:
        assert alpha_equivalent(found.apply(separate_left), expected)


@settings(max_examples=400, deadline=None)
@given(TERMS, TERMS)
def test_the_unifier_makes_both_terms_one_and_is_idempotent(left: Term, right: Term) -> None:
    left, right = undisturbed(left, right)
    found = unify_terms([left], [right])
    if found is not None:
        assert found.apply(left) == found.apply(right)
        once = found.apply(left)
        assert found.apply(once) == once


GROUND = st.sampled_from([A, B, Number(1), parse_term("f(a)"), parse_term("g(a,b)")])


@settings(max_examples=2000, deadline=None)
@given(TERMS, TERMS, st.lists(GROUND, min_size=3, max_size=3))
def test_the_unifier_is_most_general_every_other_unifier_is_an_instance_of_it(
    left: Term, right: Term, values: list[Symbol]
) -> None:
    left, right = undisturbed(left, right)
    names = dict.fromkeys((*variables(left), *variables(right)))
    other = Substitution({v: values[i % len(values)] for i, v in enumerate(names)})
    ground = other.apply(left)
    if ground == other.apply(right):
        found = unify_terms([left], [right])
        assert found is not None
        assert isinstance(ground, Symbol)
        assert reference_instance(found.apply(left), ground) == ground


@settings(max_examples=400, deadline=None)
@given(
    TERMS,
    st.sampled_from([A, B, parse_term("f(a)"), parse_term("f(g(a,b),a)"), parse_term("-f(a)")]),
)
def test_against_a_ground_pattern_unify_and_mgu_find_the_same_unifier(
    term: Term, ground: Symbol
) -> None:
    term, _ = undisturbed(term, ground)
    pattern, fact = Pattern("p", (term,)), Pattern("p", (ground,))
    shared, apart = unify(pattern, fact), mgu(pattern, fact)
    assert (shared is None) is (apart is None)
    if shared is not None and apart is not None:
        assert pattern.apply(shared) == fact
        assert apart.instance == fact
