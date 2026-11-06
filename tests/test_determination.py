import pytest

from elenctic.determination import (
    AnswerSet,
    AnswerSets,
    Conclusion,
    Consistent,
    Exhausted,
    Truncation,
    WorldView,
    option,
    world_view,
)
from elenctic.literals import Literal

P, Q = Literal("p"), Literal("q")


def answer_set(*atoms: Literal, shown: tuple[Literal, ...] | None = None) -> AnswerSet:
    return AnswerSet(frozenset(atoms), frozenset(atoms if shown is None else shown))


def test_an_exhausted_search_yields_the_world_view_of_its_answer_sets() -> None:
    found = Consistent(AnswerSets(answer_set(P, Q), (answer_set(P),)), Exhausted.EXHAUSTED)
    assert world_view(found) == WorldView(frozenset({frozenset({P, Q}), frozenset({P})}))


def test_a_truncated_search_yields_no_world_view_only_what_cut_it_short() -> None:
    found = Consistent(AnswerSets(answer_set(P)), Truncation.MAX_SECONDS)
    assert world_view(found) is Truncation.MAX_SECONDS


def test_the_world_view_reads_full_answer_sets_unless_shown_is_asked() -> None:
    found = Consistent(AnswerSets(answer_set(P, Q, shown=(P,))), Exhausted.EXHAUSTED)
    assert world_view(found) == WorldView(frozenset({frozenset({P, Q})}))
    assert world_view(found, shown=True) == WorldView(frozenset({frozenset({P})}))


def test_the_cautious_consequences_are_the_intersection_and_the_brave_the_union() -> None:
    view = WorldView(frozenset({frozenset({P, Q}), frozenset({P})}))
    assert (view.cautious, view.brave) == (frozenset({P}), frozenset({P, Q}))


def test_a_world_view_has_a_member() -> None:
    with pytest.raises(ValueError, match="no answer set"):
        WorldView(frozenset())


def test_a_conclusion_is_exhausted_or_a_truncation() -> None:
    conclusions: tuple[Conclusion, ...] = (Exhausted.EXHAUSTED, *Truncation)
    assert len(set(conclusions)) == 4


def test_a_truncation_is_named_for_the_limit_that_cut_the_search() -> None:
    assert [str(cut) for cut in Truncation] == ["max_answer_sets", "max_seconds", "interrupted"]


def test_a_limit_is_offered_as_the_option_named_for_what_it_bounds() -> None:
    assert option(Truncation.MAX_ANSWER_SETS) == "--max-answer-sets"
    assert option(Truncation.MAX_SECONDS) == "--max-seconds"
