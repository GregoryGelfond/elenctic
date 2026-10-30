from elenctic.spans import Diagnostic, Position, Severity, Span, diagnose


def test_a_located_error_becomes_a_diagnostic_with_its_span() -> None:
    message = "<string>:1:4-5: error: syntax error, unexpected ., expecting ) or ;\n"
    assert diagnose(message) == (
        Diagnostic(
            Span("<string>", Position(1, 4), Position(1, 5)),
            Severity.ERROR,
            "syntax error, unexpected ., expecting ) or ;",
        ),
    )


def test_a_note_line_is_its_own_diagnostic() -> None:
    message = (
        "f.lp:1:1-14: error: unsafe variables in:\n  p(X):-q(Y).\nf.lp:1:3-4: note: 'X' is unsafe\n"
    )
    first, second = diagnose(message)
    assert (first.severity, second.severity) == (Severity.ERROR, Severity.NOTE)
    assert second.span == Span("f.lp", Position(1, 3), Position(1, 4))
    assert first.message == "unsafe variables in:\n  p(X):-q(Y)."


def test_a_span_across_lines_reads_both_ends() -> None:
    (found,) = diagnose("f.lp:2:3-4:5: warning: atom does not occur in any rule head\n")
    assert found.span == Span("f.lp", Position(2, 3), Position(4, 5))
    assert found.severity is Severity.WARNING


def test_an_unlocated_message_is_kept_whole() -> None:
    (found,) = diagnose("something went wrong")
    assert found.span == Span("", Position(1, 1), Position(1, 1))
    assert found.message == "something went wrong"


def test_a_span_prints_as_editors_expect() -> None:
    assert str(Span("f.lp", Position(2, 3), Position(2, 9))) == "f.lp:2:3-9"
    assert str(Span("f.lp", Position(2, 3), Position(4, 5))) == "f.lp:2:3-4:5"
