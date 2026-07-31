"""What a diagnostic does with a set the program made too big to read.

A check renders the set it judged against, and a program decides how large that is: a cautious
reading over a big fact base is the whole fact base. Nobody reads a line of a hundred thousand
atoms, and whatever is on the other end of the pipe — a CI log, an editor panel — has to hold it.
"""

import pytest
from clingo import Function, Symbol

from elenctic.checks import _SHOWN_MEMBERS, _show_set
from elenctic.terms import parse_term


def _atoms(count: int) -> list[Symbol]:
    return [Function("p", [Function(f"a{index:05d}")]) for index in range(count)]


def test_a_small_set_is_shown_whole() -> None:
    # The ordinary diagnostic is unchanged: eliding is for the case that cannot be read anyway.
    rendered = _show_set(_atoms(3))
    assert rendered == "{ p(a00000), p(a00001), p(a00002) }"
    assert "more" not in rendered


def test_an_oversized_set_is_elided_and_counted() -> None:
    rendered = _show_set(_atoms(_SHOWN_MEMBERS + 500))
    assert rendered.count("p(a") == _SHOWN_MEMBERS, "only the cap's worth of members is shown"
    assert "(+500 more)" in rendered, "the remainder is counted, never silently dropped"


def test_what_is_shown_does_not_depend_on_the_search() -> None:
    # Members are rendered sorted, so two runs that found the same set in a different order show
    # the same members — an elided diagnostic still has to be stable.
    atoms = _atoms(_SHOWN_MEMBERS + 10)
    assert _show_set(atoms) == _show_set(reversed(atoms))


def test_a_term_parse_failure_carries_clingos_reason() -> None:
    # Without a logger clingo writes its own reason to stderr, outside elenctic's framing. It now
    # rides the raised error instead, so one channel carries every diagnostic.
    with pytest.raises(RuntimeError) as caught:
        parse_term("p(")
    assert str(caught.value), "the failure must say something, not just have a type"
    assert "syntax error" in str(caught.value).lower()
