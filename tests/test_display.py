"""Text from a corpus is made legible before it is shown.

Everything elenctic prints about a case is influenced by the case: its path, its ``@note`` prose,
the atoms in its answer sets, and the solver's own diagnostics about it. A corpus is untrusted
input, so that text can carry terminal control sequences — and elenctic's whole product is a
verdict a reader can believe. A corpus that can move the cursor, clear the screen, or overwrite a
line can make a failing run read as a passing one.
"""

import codecs

from hypothesis import given, strategies as st

from elenctic.display import legible


@given(st.text())
def test_no_text_at_all_comes_back_as_more_than_one_line(text: str) -> None:
    # The postcondition over the whole space rather than over the specimens below, which is what a
    # stated invariant is owed and what hypothesis is already a dependency here for.
    #
    # `splitlines` rather than a search for "\n". They are not the same question: `splitlines` ends
    # a line on \v \f \x1c \x1d \x1e \x85 U+2028 and U+2029 as well, and the postcondition is about
    # every one of them -- `textwrap.indent`, which one caller composes this with, splits the same
    # way. Asserting only the newline would leave the rest to be asked separately.
    assert len(legible(text).splitlines()) <= 1


def test_ordinary_text_is_unchanged() -> None:
    # The common case must cost nothing: sanitizing is not an excuse to mangle a diagnostic.
    for text in ("@cautious: { tea } ⊄ ⋂ AS(P)", "encodings/drinks/drinks.lp", "1/2 passed"):
        assert legible(text) == text


def test_an_escape_sequence_cannot_reach_the_terminal() -> None:
    # ESC is the lever for every ANSI sequence: colour, cursor movement, screen clearing.
    assert "\x1b" not in legible("before\x1b[2J\x1b[Hafter")
    assert "before" in legible("before\x1b[2J\x1b[Hafter")


def test_a_carriage_return_cannot_overwrite_what_was_already_printed() -> None:
    # \r alone returns the cursor to the start of the line, so the next characters replace what is
    # there. That is how a rendered FAIL is turned into something else without clearing the screen.
    assert "\r" not in legible("FAIL\rPASS")


def test_the_separators_that_split_a_line_are_escaped() -> None:
    # These are line boundaries to Python's splitlines but not to clingo, to git diff, or to a
    # reader. Left intact they let a contract read as one thing and behave as another.
    for separator in ("\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", " ", " "):
        assert separator not in legible(f"a{separator}b")


def test_the_ascii_space_is_the_only_separator_that_survives() -> None:
    # The boundary `str.isprintable` sits on, and the whole of the predicate. The ASCII space is
    # printable by that method's own definition; no other separator is. The predicate used to carry
    # `or character == " "` beside it, which over every codepoint there is changes no answer -- so
    # what read as the rule being widened was the rule being said twice, and the second saying gave
    # a reason that is not a fact.
    assert legible("a b") == "a b"
    for separator in (" ", " ", "　"):  # Zs, every one of them but U+0020
        assert separator not in legible(f"a{separator}b")


def test_a_newline_is_escaped_like_every_other_separator() -> None:
    # It was once let through, on the reasoning that adding a line is harmless beside overwriting
    # one -- "a reader who cannot trust line counts can still trust every line's contents". That is
    # false: the report's structure IS its line boundaries, so text that can add a line can write a
    # row. Measured, a file name carrying one forges a [PASS] beside the [FAIL] the case earned.
    # No new escape shape for it: `\x0a` is the same alphabet as every other control character.
    assert legible("x\n  [PASS] @expect sat (line 1): a model exists") == (
        "x\\x0a  [PASS] @expect sat (line 1): a model exists"
    )


def test_no_text_a_corpus_chose_comes_back_holding_a_line_break() -> None:
    # The postcondition, stated over the boundary's every position rather than over one specimen of
    # it: a caller interpolating this into a formatted line needs to know it stays one line, and
    # could not be told so while newlines passed through. Where a line break is CONTENT -- a
    # solver's own multi-line diagnostic -- it is the renderer that re-emits it, under a mark of
    # elenctic's own; that is a question about layout, and this function has no layout.
    for text in ("a\nb", "\n", "a\n", "\nb", "a\n\nb"):
        assert "\n" not in legible(text)


def test_what_was_escaped_is_still_readable() -> None:
    # An escaped sequence is shown, not dropped: a reader should be able to see that a corpus tried
    # something, rather than find text silently missing.
    assert legible("x\x1by") == "x\\x1by"


def test_an_escape_says_where_it_ends() -> None:
    # `\x` means EXACTLY two hex digits wherever a reader has met it. A single \x form for every
    # codepoint runs past two for anything above U+00FF, so U+2028 rendered `\x2028` reads as a
    # space followed by a literal "28" -- a reader decodes it wrongly, which is not legibility.
    # The width is fixed by the codepoint, in Python's own three shapes.
    assert legible("\x1b") == "\\x1b"  # ≤ U+00FF: two digits
    assert legible("\x85") == "\\x85"
    assert legible(" ") == "\\u2028"  # ≤ U+FFFF: four
    assert legible("") == "\\ue000"
    assert legible("\U0010ffff") == "\\U0010ffff"  # above: eight


def test_two_different_strings_never_render_the_same() -> None:
    # A backslash is printable, so leaving it alone made the encoding non-injective: a path holding
    # a real ESC and a path holding the four characters \ x 1 b rendered identically, in the report
    # AND in the published document's `source` field, so two distinct files were indistinguishable.
    # Worse for a consumer than mere ambiguity: decoding the escapes to recover the real path turns
    # the second back into a real ESC and feeds it to its own terminal.
    real_escape = legible("a\x1b[31mred")
    literal_text = legible("a\\x1b[31mred")
    assert real_escape != literal_text
    assert "\x1b" not in real_escape  # and the sanitizing itself still holds on both
    assert "\x1b" not in literal_text


def test_an_escape_decodes_back_to_what_the_corpus_held() -> None:
    # The consumer's side of injectivity: a reader who un-escapes gets the original back, rather
    # than a string that merely looks plausible.
    for original in ("a\x1b[31mred", "a\\x1b[31mred", "back\\slash", "plain/path.lp"):
        assert codecs.decode(legible(original), "unicode_escape") == original
