"""The machine-readable report: what a consumer is promised, asserted against the document.

A published contract, so its field names and its closed vocabularies are pinned here rather than
left to follow whatever the projection happens to emit — a respelling has to be a deliberate edit
in one place, not a silent consequence of renaming a Python attribute.

Assertions are made against the document rendered and read back, which is the form a consumer
actually meets: a value that survives the projection but not the rendering would otherwise pass.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from elenctic.checks import CheckReport
from elenctic.discovery import Case
from elenctic.expectation import Unsat
from elenctic.json_report import SCHEMA_VERSION, as_json, dumps
from elenctic.outcome import (
    CaseOutcome,
    ErrorKind,
    ErrorRecord,
    HygieneKind,
    HygieneRecord,
    Invocation,
    RunOutcome,
    Scope,
    Severity,
)
from elenctic.result import Conclusion, Verdict

_INVOCATION = Invocation(target=Path("corpus"), strict=False, budget=10.0, deadline=None)


def _case(
    verdict: Verdict = Verdict.PASS,
    *,
    message: str = "the diagnostic",
    subject: str = "",
    conclusion: Conclusion = Conclusion.EXHAUSTED,
    path: Path = Path("a.lp"),
) -> CaseOutcome:
    return CaseOutcome(
        case=Case(path, "clingo", Unsat(expect_line=1), frozenset()),
        reports=(
            CheckReport(
                verdict=verdict,
                label="@expect unsat",
                message=message,
                subject=subject,
                line=1,
                conclusion=conclusion,
            ),
        ),
    )


def _error(
    kind: ErrorKind = ErrorKind.PROGRAM,
    *,
    scope: Scope = Scope.CASE,
    source: Path | None = Path("a.lp"),
    message: str = "the program will not ground",
) -> ErrorRecord:
    return ErrorRecord(kind=kind, scope=scope, source=source, message=message)


def _observation(
    severity: Severity = Severity.WARNING,
    *,
    kind: HygieneKind = HygieneKind.ORPHAN_LIBRARY,
    message: str = "nothing includes it",
) -> HygieneRecord:
    return HygieneRecord(kind=kind, severity=severity, source=Path("lib.lp"), message=message)


def _run(
    *,
    cases: tuple[CaseOutcome, ...] = (),
    errors: tuple[ErrorRecord, ...] = (),
    hygiene: tuple[HygieneRecord, ...] = (),
) -> RunOutcome:
    return RunOutcome(cases=cases, errors=errors, hygiene=hygiene)


def _document(outcome: RunOutcome, invocation: Invocation = _INVOCATION) -> Any:
    """The document as a consumer receives it: projected, rendered, and read back."""
    return json.loads(dumps(as_json(outcome, invocation)))


def test_the_document_carries_exactly_the_promised_fields() -> None:
    document = _document(_run(cases=(_case(),)))
    assert set(document) == {
        "schema_version",
        "invocation",
        "summary",
        "cases",
        "errors",
        "hygiene",
    }
    assert document["schema_version"] == SCHEMA_VERSION
    assert set(document["invocation"]) == {"target", "strict", "budget", "deadline"}
    assert set(document["summary"]) == {
        "total",
        "passed",
        "failed",
        "undecided",
        "errors",
        "hygiene",
    }


def test_a_case_and_its_checks_carry_exactly_the_promised_fields() -> None:
    (case,) = _document(_run(cases=(_case(),)))["cases"]
    assert set(case) == {"source", "solver", "verdict", "checks"}
    (check,) = case["checks"]
    assert set(check) == {"tag", "subject", "status", "message", "line", "conclusion"}
    assert case["source"] == "a.lp"
    assert case["solver"] == "clingo"
    assert check["tag"] == "@expect unsat"
    assert check["line"] == 1


def test_an_error_and_an_observation_carry_exactly_the_promised_fields() -> None:
    document = _document(_run(errors=(_error(),), hygiene=(_observation(),)))
    (error,) = document["errors"]
    (observation,) = document["hygiene"]
    assert set(error) == {"kind", "scope", "source", "message"}
    assert set(observation) == {"kind", "severity", "source", "message"}
    assert error["source"] == "a.lp"
    assert error["message"] == "the program will not ground"
    assert observation["source"] == "lib.lp"


def test_the_invocation_is_the_one_the_run_was_given() -> None:
    given = Invocation(target=Path("elsewhere"), strict=True, budget=2.5, deadline=60.0)
    assert _document(_run(), given)["invocation"] == {
        "target": "elsewhere",
        "strict": True,
        "budget": 2.5,
        "deadline": 60.0,
    }


def test_a_deadline_that_was_not_set_is_null_rather_than_absent() -> None:
    # A consumer reading a field that is sometimes missing has to write two readings of it, and the
    # default being off is exactly when that would bite.
    invocation = _document(_run())["invocation"]
    assert "deadline" in invocation
    assert invocation["deadline"] is None


@pytest.mark.parametrize(
    ("verdict", "written"),
    [(Verdict.PASS, "PASS"), (Verdict.FAIL, "FAIL"), (Verdict.UNDECIDED, "UNDECIDED")],
)
def test_a_verdict_is_written_the_way_a_consumer_was_promised(
    verdict: Verdict, written: str
) -> None:
    (case,) = _document(_run(cases=(_case(verdict),)))["cases"]
    assert case["verdict"] == written
    assert case["checks"][0]["status"] == written


@pytest.mark.parametrize(
    ("conclusion", "written"),
    [
        (Conclusion.EXHAUSTED, "exhausted"),
        (Conclusion.INCOMPLETE, "incomplete"),
        (Conclusion.INTERRUPTED, "interrupted"),
    ],
)
def test_how_a_search_ended_is_written_the_way_a_consumer_was_promised(
    conclusion: Conclusion, written: str
) -> None:
    (case,) = _document(_run(cases=(_case(conclusion=conclusion),)))["cases"]
    assert case["checks"][0]["conclusion"] == written


@pytest.mark.parametrize(
    ("kind", "written"),
    [
        (ErrorKind.CONTRACT, "ContractError"),
        (ErrorKind.DISCOVERY, "DiscoveryError"),
        (ErrorKind.PROGRAM, "ProgramError"),
        (ErrorKind.DEADLINE, "DeadlineError"),
        (ErrorKind.RESOURCE, "ResourceError"),
        (ErrorKind.HARNESS, "HarnessError"),
    ],
)
def test_where_a_fault_lies_is_written_the_way_a_consumer_was_promised(
    kind: ErrorKind, written: str
) -> None:
    (error,) = _document(_run(errors=(_error(kind),)))["errors"]
    assert error["kind"] == written


@pytest.mark.parametrize(("scope", "written"), [(Scope.CORPUS, "corpus"), (Scope.CASE, "case")])
def test_what_a_fault_stopped_is_written_the_way_a_consumer_was_promised(
    scope: Scope, written: str
) -> None:
    (error,) = _document(_run(errors=(_error(scope=scope),)))["errors"]
    assert error["scope"] == written


@pytest.mark.parametrize(
    ("severity", "written"),
    [(Severity.SILENT, "silent"), (Severity.WARNING, "warning"), (Severity.ERROR, "error")],
)
def test_how_loudly_an_observation_was_graded_is_written_the_way_a_consumer_was_promised(
    severity: Severity, written: str
) -> None:
    (observation,) = _document(_run(hygiene=(_observation(severity),)))["hygiene"]
    assert observation["severity"] == written


@pytest.mark.parametrize(
    ("kind", "written"),
    [
        (HygieneKind.ORPHAN_LIBRARY, "orphan_library"),
        (HygieneKind.UNDECLARED_SOLVER, "undeclared_solver"),
    ],
)
def test_what_was_observed_is_written_the_way_a_consumer_was_promised(
    kind: HygieneKind, written: str
) -> None:
    (observation,) = _document(_run(hygiene=(_observation(kind=kind),)))["hygiene"]
    assert observation["kind"] == written


def test_a_corpus_scoped_fault_names_no_file_rather_than_an_empty_one() -> None:
    (error,) = _document(_run(errors=(_error(scope=Scope.CORPUS, source=None),)))["errors"]
    assert error["source"] is None


def test_the_counts_are_the_registers_counted() -> None:
    outcome = _run(
        cases=(_case(Verdict.PASS), _case(Verdict.FAIL), _case(Verdict.UNDECIDED)),
        errors=(_error(), _error(scope=Scope.CORPUS, source=None)),
        hygiene=(_observation(),),
    )
    assert _document(outcome)["summary"] == {
        "total": 4,  # three verdicts plus the one case-scoped fault; the corpus fault cost none
        "passed": 1,
        "failed": 1,
        "undecided": 1,
        "errors": 2,
        "hygiene": 1,
    }


def test_a_source_name_that_is_not_valid_utf8_still_serializes() -> None:
    # A file name carrying a byte that is not UTF-8 decodes to a lone surrogate, which cannot be
    # encoded and would otherwise fail at the moment of writing rather than at the moment of
    # reading. Everything the corpus controls passes through the same sanitizer first.
    text = dumps(as_json(_run(errors=(_error(source=Path("case\udcff.lp")),)), _INVOCATION))
    text.encode("utf-8")  # must not raise
    assert json.loads(text)["errors"][0]["source"] == "case\\xdcff.lp"


def test_a_line_separator_in_corpus_text_does_not_reach_the_document() -> None:
    # U+2028 and U+2029 end a line inside a string for some consumers of JSON, which would split a
    # document that is required to be exactly one. Written as escapes rather than as themselves: a
    # literal one in this file would be invisible to anyone reviewing the test, and Python's own
    # line splitting would treat it as the end of this line.
    separators = "\u2028\u2029"
    text = dumps(as_json(_run(errors=(_error(message=f"broke{separators}here"),)), _INVOCATION))
    assert not set(separators) & set(text), "no raw line separator reaches the document"
    assert json.loads(text)["errors"][0]["message"] == "broke\\x2028\\x2029here"


@pytest.mark.parametrize(
    "hostile",
    ["\x1b[2J", "a\rb", "\x00"],
    ids=["clears-the-screen", "overwrites-the-line", "a-null-byte"],
)
def test_text_a_terminal_would_act_on_does_not_reach_the_document(hostile: str) -> None:
    # A document is read by people too — pasted into a terminal, echoed by a tool. The guarantee
    # the human render has is the one this has.
    outcome = _run(cases=(_case(Verdict.FAIL, message=f"found {hostile}", subject=hostile),))
    (case,) = _document(outcome)["cases"]
    assert hostile not in case["checks"][0]["message"]
    assert hostile not in case["checks"][0]["subject"]


def test_every_field_the_corpus_can_reach_is_sanitized() -> None:
    # A sweep rather than a field at a time, because which fields a corpus can reach is a question
    # whose answer changes: a new one has to inherit the guarantee, and this is what says so. The
    # solver name is the one string here a corpus cannot choose freely — it is validated against a
    # closed registry before a case is built — so it is absent by construction, not by omission.
    #
    # A lone surrogate, the two line separators, an escape introducer and a null byte. The escape
    # sequence's payload is left in the input deliberately: once the introducer is escaped, "[2J"
    # is three ordinary characters, and demanding their absence would be demanding that the text be
    # dropped rather than defanged.
    acted_on = "\udcff\u2028\u2029\x1b\x00"
    hostile = f"{acted_on}[2J"
    outcome = _run(
        cases=(_case(Verdict.FAIL, message=hostile, subject=hostile, path=Path(hostile)),),
        errors=(_error(source=Path(hostile), message=hostile),),
        hygiene=(_observation(message=hostile),),
    )
    invocation = Invocation(target=Path(hostile), strict=False, budget=1.0, deadline=None)
    text = dumps(as_json(outcome, invocation))
    text.encode("utf-8")  # a lone surrogate anywhere would make the document unwritable
    assert not set(acted_on) & set(text), "no field carries a character a reader would act on"
    assert text.count("\\xdcff") == 7, "and every one of them still says something was there"


def test_text_the_sanitizer_leaves_alone_is_written_as_itself() -> None:
    # The counterpart of the sweep: escaping is for what a reader's tooling would act on, not for
    # everything unfamiliar. A diagnostic quoting the notation elenctic itself prints stays legible.
    text = dumps(as_json(_run(errors=(_error(message="{ tea } ⊄ ⋂ AS(P)"),)), _INVOCATION))
    assert "{ tea } ⊄ ⋂ AS(P)" in text, "printable text is not escaped into unreadability"


def test_the_same_outcome_serializes_identically_twice() -> None:
    outcome = _run(
        cases=(_case(Verdict.FAIL), _case(Verdict.PASS)),
        errors=(_error(),),
        hygiene=(_observation(),),
    )
    assert dumps(as_json(outcome, _INVOCATION)) == dumps(as_json(outcome, _INVOCATION))


def test_the_registers_keep_the_run_s_own_order() -> None:
    # Nothing is sorted: a case's position in its array is its identity within the document, so a
    # consumer that stored a position must find the same case there on the same input.
    # Named so that sorting them would visibly reorder them: a fixture already in sorted order
    # cannot tell "kept the run's order" apart from "sorted it".
    outcome = _run(
        errors=(_error(message="third"), _error(message="first"), _error(message="second"))
    )
    assert [error["message"] for error in _document(outcome)["errors"]] == [
        "third",
        "first",
        "second",
    ]


def test_the_rendered_document_is_one_indented_object_ending_in_one_newline() -> None:
    text = dumps(as_json(_run(cases=(_case(),)), _INVOCATION))
    assert text.endswith("}\n")
    assert not text.endswith("}\n\n")
    assert isinstance(json.loads(text), dict)
    # Written to be read as well as parsed: a report is something a person opens after a run.
    assert '\n  "schema_version"' in text
