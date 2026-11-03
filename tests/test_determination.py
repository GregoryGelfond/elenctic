import pytest

from elenctic.determination import (
    Conclusion,
    Consistent,
    Exhausted,
    Model,
    Models,
    Truncation,
    WorldView,
    world_view,
)
from elenctic.literals import Literal

P, Q = Literal("p"), Literal("q")


def answer_set(*atoms: Literal, shown: tuple[Literal, ...] | None = None) -> Model:
    return Model(frozenset(atoms), frozenset(atoms if shown is None else shown))


def test_an_exhausted_search_yields_the_world_view_of_its_answer_sets() -> None:
    found = Consistent(Models(answer_set(P, Q), (answer_set(P),)), Exhausted.EXHAUSTED)
    assert world_view(found) == WorldView(frozenset({frozenset({P, Q}), frozenset({P})}))


def test_a_truncated_search_yields_no_world_view_only_what_cut_it_short() -> None:
    found = Consistent(Models(answer_set(P)), Truncation.BUDGET)
    assert world_view(found) is Truncation.BUDGET


def test_the_world_view_reads_the_shown_atoms_unless_told_otherwise() -> None:
    found = Consistent(Models(answer_set(P, Q, shown=(P,))), Exhausted.EXHAUSTED)
    assert world_view(found) == WorldView(frozenset({frozenset({P})}))
    assert world_view(found, shown=False) == WorldView(frozenset({frozenset({P, Q})}))


def test_the_cautious_consequences_are_the_intersection_and_the_brave_the_union() -> None:
    view = WorldView(frozenset({frozenset({P, Q}), frozenset({P})}))
    assert (view.cautious, view.brave) == (frozenset({P}), frozenset({P, Q}))


def test_a_world_view_has_a_member() -> None:
    with pytest.raises(ValueError, match="no answer set"):
        WorldView(frozenset())


def test_a_conclusion_is_exhausted_or_a_truncation() -> None:
    conclusions: tuple[Conclusion, ...] = (Exhausted.EXHAUSTED, *Truncation)
    assert len(set(conclusions)) == 4
