from time import perf_counter

from elenctic.program import Source
from elenctic.spans import (
    Child,
    Diagnostic,
    Position,
    Severity,
    Span,
    char_column,
    diagnose,
    failure,
    in_characters,
    note,
    split_lines,
)


def test_a_located_error_becomes_a_diagnostic_with_its_span() -> None:
    message = "<string>:1:4-5: error: syntax error, unexpected ., expecting ) or ;\n"
    assert diagnose(message) == (
        Diagnostic(
            Span("<string>", Position(1, 4), Position(1, 5)),
            Severity.ERROR,
            "syntax error, unexpected ., expecting ) or ;",
        ),
    )


def test_a_note_line_is_a_child_of_the_error_it_follows() -> None:
    message = (
        "f.lp:1:1-14: error: unsafe variables in:\n  p(X):-q(Y).\nf.lp:1:3-4: note: 'X' is unsafe\n"
    )
    first, second = diagnose(message)
    assert (first.severity, second.severity) == (Severity.ERROR, Severity.NOTE)
    assert second.span == Span("f.lp", Position(1, 3), Position(1, 4))
    assert first.message == "unsafe variables in:"
    assert first.children == (Child(Severity.NOTE, "  p(X):-q(Y)."),)


def test_a_span_across_lines_reads_both_ends() -> None:
    (found,) = diagnose("f.lp:2:3-4:5: warning: atom does not occur in any rule head\n")
    assert found.span == Span("f.lp", Position(2, 3), Position(4, 5))
    assert found.severity is Severity.WARNING


def test_an_unlocated_message_is_kept_whole() -> None:
    (found,) = diagnose("something went wrong")
    assert found.span is None
    assert found.message == "something went wrong"


def test_an_empty_message_yields_no_diagnostic() -> None:
    assert diagnose("") == ()
    assert diagnose(" \n") == ()


def test_a_span_prints_as_editors_expect() -> None:
    assert str(Span("f.lp", Position(2, 3), Position(2, 9))) == "f.lp:2:3-9"
    assert str(Span("f.lp", Position(2, 3), Position(4, 5))) == "f.lp:2:3-4:5"


def test_a_failure_is_an_error_diagnostic_at_the_span() -> None:
    where = Span("f.lp", Position(2, 3), Position(2, 9))
    assert failure(where, "expected a literal") == Diagnostic(
        where, Severity.ERROR, "expected a literal"
    )


def test_a_note_is_a_diagnostic_that_does_not_fail() -> None:
    where = Span("t.lp", Position(1, 1), Position(1, 2))
    assert note(where, "reads a hidden literal") == Diagnostic(
        where, Severity.NOTE, "reads a hidden literal"
    )


def test_char_column_maps_the_first_byte_and_zero_to_column_one() -> None:
    assert char_column("café", 1) == 1
    assert char_column("café", 0) == 1


def test_char_column_past_the_encoded_line_is_one_past_the_end() -> None:
    assert char_column("ab", 100) == 3
    assert char_column("é", len("é".encode()) + 1) == 2


def test_in_characters_reads_the_named_line_not_a_neighbour() -> None:
    raw = Span("t.lp", Position(2, 1), Position(2, 2))
    converted = in_characters(raw, "aé\ny\n")
    assert converted == Span("t.lp", Position(2, 1), Position(2, 2))


def seconds_to_locate_every_line(count: int) -> float:
    """Locate and read back each line of a program of `count` facts, as reading its rules does."""
    text = "\n".join(f"p({i})." for i in range(count))
    source = Source("<string>", {"<string>": text})
    split_lines.cache_clear()
    started = perf_counter()
    for line in range(1, count + 1):
        span = in_characters(Span("<string>", Position(line, 1), Position(line, 3)), text)
        assert source.text(span) == "p("
    return perf_counter() - started


def test_locating_eight_times_as_many_lines_takes_about_eight_times_as_long_not_sixty_four() -> (
    None
):
    small = min(seconds_to_locate_every_line(1_000) for _ in range(3))
    large = min(seconds_to_locate_every_line(8_000) for _ in range(3))
    assert large < 24 * small


def test_the_text_of_a_span_is_what_it_covers_and_empty_where_it_reaches_past_its_source() -> None:
    source = Source("t.lp", {"t.lp": "p.\nq :- p.\n"})
    assert source.text(Span("t.lp", Position(2, 1), Position(2, 3))) == "q "
    assert source.text(Span("t.lp", Position(1, 2), Position(2, 2))) == ".\nq"
    assert source.text(Span("t.lp", Position(4, 1), Position(4, 2))) == ""
    assert source.text(Span("u.lp", Position(1, 1), Position(1, 2))) == ""
