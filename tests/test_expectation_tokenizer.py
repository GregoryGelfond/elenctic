"""The tokenizer's obligations to a file it did not write.

A contract is read from a ``.lp`` file that elenctic did not author, so the tokenizer is the first
thing an unusual file meets. Three properties matter there and none of them is about parsing:

*It must finish.* The scan runs before clingo is invoked and before any budget exists, so work that
grows with the square of the file has nothing to stop it.

*Its comments must be clingo's comments.* The contract channel is comments, so wherever the two
readings disagree the result is either a contract nobody reading the file believes is in force, or
one nobody knows is missing. The four shapes below are that disagreement, one per construct of the
comment grammar; ``test_comment_lexis`` holds the grammar itself against clingo.

*Its lines must be clingo's lines.* A clingo ``%`` comment runs to a newline. If elenctic ends a
line anywhere else, a file can carry a contract that a reviewer reading the diff cannot see.
"""

import time

import pytest

from elenctic.expectation import (
    ContractError,
    _blocks,
    _lex,
    _tag_comments,
    has_contract,
    parse,
)

# Every character Python's str.splitlines treats as a line boundary and clingo does not.
_NOT_A_LINE_BREAK_TO_CLINGO = ["\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " "]


@pytest.mark.parametrize("separator", _NOT_A_LINE_BREAK_TO_CLINGO)
def test_a_contract_line_ends_where_clingo_ends_it(separator: str) -> None:
    # One physical line to clingo, to git diff, and to a reviewer — so one line here. Otherwise a
    # tag can be smuggled onto a line that reads as an innocuous comment.
    smuggled = f"% @expect sat{separator}% @count 99\n"
    assert [block.tag for block in _tag_comments(_lex(smuggled).comments)] == ["expect"]


@pytest.mark.parametrize("separator", _NOT_A_LINE_BREAK_TO_CLINGO)
def test_a_file_is_not_collected_on_a_tag_clingo_cannot_see(separator: str) -> None:
    # The collection predicate reads the same lines. A library must not become a case because of a
    # character that is invisible in review.
    assert not has_contract(f"% ordinary prose{separator}% @expect sat\n")


def test_a_trailing_tag_is_a_contract() -> None:
    # A comment after the rule on its line is the dominant ASP annotation idiom, and it was the
    # one shape read as no comment at all: the file was collected as a library and never run, and
    # where some case #includes it that is wholly silent — no warning, no failure, exit 0.
    trailing = "p(1).  % @expect sat\n"
    assert has_contract(trailing) is True
    assert [block.tag for block in _tag_comments(_lex(trailing).comments)] == ["expect"]


def test_a_contract_commented_out_in_a_block_is_not_in_force() -> None:
    # `%* … *%` is how an author turns something off. Reading a tag out of it means a contract
    # stays in force after its author has visibly disabled it.
    #
    # Both spellings, because only the second reaches the tag pattern at all: inside a block a `%`
    # opens a line comment, so the first's body begins with one and no `@` is ever at its head.
    commented_out = "%*\n% @expect sat\n% @model { a }\n*%\np(1).\n"
    assert has_contract(commented_out) is False
    assert _blocks(commented_out) == []

    inline = "%* @expect sat *%\np(1).\n"
    assert has_contract(inline) is False
    assert _blocks(inline) == []


def test_a_file_whose_comment_structure_never_closes_is_refused_not_filed_away() -> None:
    # An unterminated `%*` or `#script` swallows the rest of the file, so a contract below it is
    # not a contract — to clingo either. But answering "library" would decide that on the strength
    # of the part of the file that could not be read, and a library nothing runs is silent: the
    # contract the author is looking at would never run and the corpus would still be green.
    #
    # `100%` is what makes this ordinary rather than exotic: the `%` opens a line comment inside
    # the block, so the `*%` meant to close it is inside that comment.
    swallowed = "%* Disabled: 100% of these currently fail *%\n% @expect sat\np(1).\n"
    assert has_contract(swallowed) is True
    with pytest.raises(ContractError, match=r"^cases/x\.lp:1: unterminated `%\*`"):
        parse(swallowed, source="cases/x.lp")

    unclosed_script = "p(1).\n#script (python)\npass\n% @expect sat\n"
    assert has_contract(unclosed_script) is True
    with pytest.raises(ContractError, match=r"^cases/x\.lp:2: unterminated `#script`"):
        parse(unclosed_script, source="cases/x.lp")


def test_a_file_that_never_closes_is_refused_even_with_no_tag_below_it() -> None:
    # Otherwise the boundary between a loud failure and a silent one is *where the author happened
    # to put the first tag* relative to the unterminated construct — a coordinate nothing chose.
    assert has_contract("%* open\np(1).\n") is True
    with pytest.raises(ContractError, match=r"^line 1: unterminated `%\*`"):
        parse("%* open\np(1).\n")


def test_a_tag_inside_a_script_body_is_not_a_contract() -> None:
    # A `#script … #end.` body is opaque to clingo's lexer: `%` in it is program text, not a
    # comment. Reading a contract out of it is reading one out of a Python source line.
    script = '#script (python)\nTEMPLATE = """\n% @expect unsat\n"""\n#end.\n% @expect sat\n'
    assert [block.tag for block in _tag_comments(_lex(script).comments)] == ["expect"]
    assert _blocks(script)[0].line == 6


def test_a_litset_continuation_stops_at_program_text() -> None:
    # The continuation used to step over anything that was not a `%` line, so a comment further
    # down the file joined a litset across the rules between them — a payload the author never
    # wrote. A contract annotation is a contiguous run of comment lines.
    assert _blocks("% @model { p(1),\nq(2).\n% p(2) }\n")[0].payload == "{ p(1),"

    # And on the next line too: a rule standing between the two halves of a litset separates them
    # whether it takes a line of its own or shares one with the comment that follows it.
    assert _blocks("% @model { p(1),\nq(2).  % p(2) }\n")[0].payload == "{ p(1),"
    assert _blocks("p(1).  % @model { a,\nq(2).  % b }\n")[0].payload == "{ a,"


def test_a_continuation_may_follow_a_trailing_tag() -> None:
    # The tag names itself, so it is a tag wherever it stands; only the continuation has to begin
    # its line, because nothing in a continuation says what it is except where it sits.
    assert _blocks("p(1).  % @model { a,\n%   b }\n")[0].payload == "{ a, b }"


@pytest.mark.parametrize(
    "preceding",
    [
        pytest.param('"a string"', id="a string term"),
        pytest.param("#script(python)#end.", id="a script body"),
        pytest.param("%* a block *%", id="a block comment"),
    ],
)
def test_program_text_before_a_continuation_ends_the_run_whatever_it_is(preceding: str) -> None:
    # The scanner steps over a string and a script body in one move each, so "has anything but
    # whitespace stood on this line" has to survive those moves — otherwise a comment trailing one
    # of them reads as though it began its line, and the litset absorbs across it.
    text = f"% @model {{ a,\n{preceding}  % b }}\n"
    assert _blocks(text)[0].payload == "{ a,"


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
    # The continued region has to be an unbroken run of comment lines to be a continued region at
    # all, so that is what the load is: program text after the tag would close the litset on the
    # next line and measure nothing.
    payload = "p(1), " * 4_000  # ~24 KB, all on the tag line, brace left open
    text = "\n".join([f"% @model {{ {payload}", *["%   p(1),"] * 40_000])

    started = time.perf_counter()
    _blocks(text)
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"tokenizing took {elapsed:.1f}s — the scan is superlinear again"
