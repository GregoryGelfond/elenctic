from aspnext import Fault, Limits, Locus, Program, check, parse_contract
from aspnext.lsp import contract_diagnostics, diagnostics
from aspnext.spans import Diagnostic, Position, Severity, Span

TEXT = "% @expect sat\n% @cautious { q }\np.\n"


def test_a_failed_claim_is_an_error_at_the_claim() -> None:
    report = check(Program(TEXT, "t.lp"), limits=Limits())
    assert report is not None
    assert not isinstance(report, Fault)
    [found] = diagnostics(report)
    assert found["severity"] == 1
    assert found["range"] == {
        "start": {"line": 1, "character": 2},
        "end": {"line": 1, "character": 17},
    }
    assert str(found["message"]).startswith("@cautious { q }: ")


def test_a_fault_reports_its_own_diagnostics() -> None:
    span = Span("t.lp", Position(3, 5), Position(3, 9))
    fault = Fault(Locus.REQUEST, (Diagnostic(span, Severity.WARNING, "odd"),))
    assert diagnostics(fault) == [
        {
            "range": {
                "start": {"line": 2, "character": 4},
                "end": {"line": 2, "character": 8},
            },
            "severity": 2,
            "message": "odd",
            "source": "aspnext",
        }
    ]


def test_a_passing_report_has_no_diagnostics() -> None:
    report = check(Program("% @expect sat\np.\n", "t.lp"), limits=Limits())
    assert report is not None
    assert not isinstance(report, Fault)
    assert diagnostics(report) == []


def test_contract_errors_are_placed_like_any_other() -> None:
    [found] = contract_diagnostics(
        parse_contract("% @expect sat\n% @count x\n", "t.lp").diagnostics
    )
    assert found["range"]["start"] == {"line": 1, "character": 2}  # type: ignore[index]
