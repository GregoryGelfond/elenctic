"""Text from a corpus is made legible before it is shown.

Everything elenctic prints about a case is influenced by the case: its path, its ``@note`` prose,
the atoms in its answer sets, and the solver's own diagnostics about it. A corpus is untrusted
input, so that text can carry terminal control sequences — and elenctic's whole product is a
verdict a reader can believe. A corpus that can move the cursor, clear the screen, or overwrite a
line can make a failing run read as a passing one.
"""

from elenctic.display import legible


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


def test_a_newline_survives() -> None:
    # Deliberately kept. A solver diagnostic is legitimately multi-line, and the friendly-error bar
    # is worth more than closing the one thing a newline still permits: adding a line. It cannot
    # rewrite or conceal one, which is what the escapes above are for.
    assert legible("error: file could not be opened:\n  missing.lp") == (
        "error: file could not be opened:\n  missing.lp"
    )


def test_what_was_escaped_is_still_readable() -> None:
    # An escaped sequence is shown, not dropped: a reader should be able to see that a corpus tried
    # something, rather than find text silently missing.
    assert legible("x\x1by") == "x\\x1by"
