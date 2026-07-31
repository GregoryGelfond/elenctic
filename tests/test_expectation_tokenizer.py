"""The tokenizer's two obligations to a file it did not write.

A contract is read from a ``.lp`` file that elenctic did not author, so the tokenizer is the first
thing an unusual file meets. Two properties matter there and neither is about parsing:

*It must finish.* The scan runs before clingo is invoked and before any budget exists, so work that
grows with the square of the file has nothing to stop it.

*Its lines must be clingo's lines.* A clingo ``%`` comment runs to a newline. If elenctic ends a
line anywhere else, a file can carry a contract that a reviewer reading the diff cannot see.
"""

import time

import pytest

from elenctic.expectation import _blocks, _tag_lines, has_contract

# Every character Python's str.splitlines treats as a line boundary and clingo does not.
_NOT_A_LINE_BREAK_TO_CLINGO = ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]


@pytest.mark.parametrize("separator", _NOT_A_LINE_BREAK_TO_CLINGO)
def test_a_contract_line_ends_where_clingo_ends_it(separator: str) -> None:
    # One physical line to clingo, to git diff, and to a reviewer — so one line here. Otherwise a
    # tag can be smuggled onto a line that reads as an innocuous comment.
    smuggled = f"% @expect sat{separator}% @count 99\n"
    assert [block.tag for block in _tag_lines(smuggled)] == ["expect"]


@pytest.mark.parametrize("separator", _NOT_A_LINE_BREAK_TO_CLINGO)
def test_a_file_is_not_collected_on_a_tag_clingo_cannot_see(separator: str) -> None:
    # The collection predicate reads the same lines. A library must not become a case because of a
    # character that is invisible in review.
    assert not has_contract(f"% ordinary prose{separator}% @expect sat\n")


def test_an_ordinary_multi_line_litset_still_joins() -> None:
    # The behaviour all of this exists to serve, unchanged: a litset continued across % lines while
    # its brace is open.
    blocks = _blocks("% @model { a,\n%   b,\n%   c }\n")
    assert len(blocks) == 1
    assert blocks[0].payload == "{ a, b, c }"


def test_prose_after_a_closed_litset_is_left_alone() -> None:
    # The other half of the join rule: once the brace closes, following % lines are comments again.
    blocks = _blocks("% @model { a }\n% just a remark\n")
    assert blocks[0].payload == "{ a }"


def test_a_long_file_under_an_open_litset_finishes() -> None:
    # The scan used to re-read the whole accumulated payload for every following line, and to
    # rebuild it with a copy per continuation — two quadratics, both reachable before clingo is
    # invoked and before any budget applies. The bound below is deliberately loose: linear work
    # here is milliseconds, and the quadratic it guards against was minutes, so the margin absorbs
    # any plausible machine without the test becoming a stopwatch.
    payload = "p(1), " * 4_000  # ~24 KB, all on the tag line, brace left open
    text = "\n".join([f"% @model {{ {payload}", *["fact(1)."] * 40_000])

    started = time.perf_counter()
    _blocks(text)
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"tokenizing took {elapsed:.1f}s — the scan is superlinear again"
