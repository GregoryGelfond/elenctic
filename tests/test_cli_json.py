"""End to end under ``--format json``: one document on standard output, and nothing else there.

The consumer this format exists for parses standard output and has nothing else to go on. So what
is asserted here is not only that the document is right but that it is *alone*: a run writes its
report as it goes, the grounder writes at a level a Python-side redirect does not reach, and one
foreign byte costs the consumer the whole document rather than a line of it.

**Every test here runs elenctic as a process**, and that is not a stylistic choice. The guarantee is
that the process's standard output carries the document, and it is kept by moving the descriptor
that standard output *is*. A test runner capturing output replaces ``sys.stdout`` with an object of
its own writing to a file of its own, which no longer travels through that descriptor — so an
in-process test watches a stream the guarantee never touches and reports a clean standard output
whether or not the guarantee holds. Both capture fixtures share that blind spot here; the only
instrument that can see this is a real process.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from elenctic.json_report import dumps

_PASSES = "% @expect sat\n% @count 2\n\n1 { tea; coffee } 1.\n#show tea/0.\n#show coffee/0.\n"
_FAILS = "% @expect sat\n% @cautious { tea }\n\nbiscuit.\n#show biscuit/0.\n"
_WILL_NOT_GROUND = "% @expect sat\n% @count 1\n\nq(1).\np(X) :- q(Y).\n"
_ORPHAN = "% a contract-free file nothing includes.\nhelper(1).\n"

# The child: elenctic's own console entry, given the arguments this process passes after the
# program text. A prelude may stand a fault in front of it, which is how a register that only a
# fault can reach gets exercised without one being contrived inside the corpus.
_CHILD = """
import sys
{prelude}
from elenctic.cli import main

sys.exit(main(sys.argv[1:]))
"""

_ALLOCATION_FAILS = """
import elenctic.cli

def _out_of_memory(invocation):
    raise MemoryError

elenctic.cli.run_corpus = _out_of_memory
"""

_NO_REGISTER_ANTICIPATED_THIS = """
import elenctic.cli

def _unanticipated(invocation):
    raise ZeroDivisionError("something no register was written for")

elenctic.cli.run_corpus = _unanticipated
"""

# A packaged description that is present and unreadable as text, which is the one fault in printing
# it that is not an OSError — so it passes the handler that names a mis-shaped environment and
# reaches the backstop instead, before a corpus has been looked at.
_DESCRIPTION_IS_NOT_TEXT = """
import elenctic.cli

def _unreadable():
    raise ValueError("the packaged description is not valid text")

elenctic.cli.schema_text = _unreadable
"""


class _Streams(NamedTuple):
    out: str
    err: str
    status: int


def _corpus(root: Path, **cases: str) -> Path:
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return root


def _run(target: Path, *flags: str, prelude: str = "") -> _Streams:
    """One invocation of elenctic, as a process, with its two streams kept apart."""
    finished = subprocess.run(
        [sys.executable, "-c", _CHILD.format(prelude=prelude), str(target), *flags],
        capture_output=True,
        text=True,
        check=False,
    )
    return _Streams(finished.stdout, finished.stderr, finished.returncode)


def _reported(target: Path, *flags: str, prelude: str = "") -> _Streams:
    return _run(target, "--format", "json", *flags, prelude=prelude)


def _document(out: str) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(out)
    return parsed


def _status_off_the_document(document: dict[str, Any]) -> int:
    """The exit status as a consumer holding only the document reconstructs it.

    The document promises this ladder is readable from its own fields, which is what lets a stored
    report be graded long after the process that produced it is gone. Written out here rather than
    imported, so that what is checked is the promise and not the implementation agreeing with
    itself.
    """
    if any(error["is_elenctic_bug"] for error in document["errors"]):
        return 3
    if document["errors"] or any(record["grade"] == "error" for record in document["hygiene"]):
        return 2
    if any(case["verdict"] != "pass" for case in document["cases"]):
        return 1
    return 0


def test_standard_output_carries_one_document_and_nothing_else(tmp_path: Path) -> None:
    # The corpus is chosen so the human run has plenty to say: a case that FAILs is rendered, an
    # orphan library is observed, and every run writes a summary line. All of it is prose, and one
    # byte of it beside the document costs the consumer the parse rather than a line.
    target = _corpus(tmp_path, passes=_PASSES, fails=_FAILS, orphan_library=_ORPHAN)

    streams = _reported(target)

    assert streams.out == dumps(_document(streams.out)), (
        "standard output is exactly the document, rendered as the package renders it — no prose "
        "before it, nothing appended, and one trailing newline"
    )
    assert streams.status == 1, "a case decided wrong, and nothing else went wrong"
    assert "FAIL" in streams.err, "the human report is moved to standard error, not discarded"
    assert "1/2 passed" in streams.err, "including the summary the run writes at the end"


@pytest.mark.parametrize(
    ("described", "cases", "flags", "expected"),
    [
        ("a corpus where every case passes", {"passes": _PASSES}, (), 0),
        ("a case that decided wrong", {"fails": _FAILS}, (), 1),
        ("a case that could not be run", {"broken": _WILL_NOT_GROUND}, (), 2),
        (
            "an observation this run graded an error",
            {"passes": _PASSES, "orphan_library": _ORPHAN},
            ("--strict",),
            2,
        ),
    ],
    ids=["passing", "failing", "unrunnable", "strict-hygiene"],
)
def test_the_status_a_consumer_reads_off_the_document_is_the_status_the_process_returned(
    tmp_path: Path,
    described: str,
    cases: dict[str, str],
    flags: tuple[str, ...],
    expected: int,
) -> None:
    # A stored report outlives the process that produced it, so the document promises its own
    # grading ladder. Two readings of one run that can come to disagree are worse than one reading.
    streams = _reported(_corpus(tmp_path, **cases), *flags)

    assert streams.status == expected, described
    assert _status_off_the_document(_document(streams.out)) == streams.status, described


def test_a_corpus_that_could_not_be_discovered_still_produces_a_document(tmp_path: Path) -> None:
    # Nothing ran, so there is no verdict to report — but a consumer handed nothing at all cannot
    # tell a corpus that could not be found from a run that died before writing anything.
    streams = _reported(tmp_path / "no_such_directory")
    document = _document(streams.out)

    assert streams.status == 2
    assert document["cases"] == [], "nothing was tested, so nothing belongs in that register"
    (error,) = document["errors"]
    assert error["scope"] == "corpus", "the fault belongs to no single case"
    assert error["is_elenctic_bug"] is False
    assert document["summary"]["total"] == 0
    assert "corpus error" in streams.err


def test_a_case_that_will_not_ground_costs_only_its_own_verdict(tmp_path: Path) -> None:
    target = _corpus(tmp_path, passes=_PASSES, broken=_WILL_NOT_GROUND)

    streams = _reported(target)
    document = _document(streams.out)

    assert streams.status == 2
    (case,) = document["cases"]
    assert case["verdict"] == "pass", "a broken sibling costs a case nothing"
    (error,) = document["errors"]
    assert error["kind"] == "program", "the program under test is broken, not elenctic"
    assert error["scope"] == "case"
    assert error["source"].endswith("broken.lp")
    assert document["summary"]["total"] == 2, "both files were discovered, and both are accounted"


def test_hygiene_this_run_graded_an_error_reaches_the_document(tmp_path: Path) -> None:
    target = _corpus(tmp_path, passes=_PASSES, orphan_library=_ORPHAN)

    streams = _reported(target, "--strict")
    document = _document(streams.out)

    assert streams.status == 2, "the gate fails on a corpus-health observation under --strict"
    graded = {record["kind"]: record["grade"] for record in document["hygiene"]}
    assert graded["orphan_library"] == "error"
    assert all(case["verdict"] == "pass" for case in document["cases"]), (
        "an observation about the corpus is never a verdict about a program"
    )


def test_the_same_corpus_serializes_identically_twice(tmp_path: Path) -> None:
    # No case here is bounded by time, so nothing in the document depends on how fast the machine
    # is. A consumer diffing two reports of an unchanged corpus must see no diff — and because
    # these are two processes rather than two calls, anything ordered by a hash seed would show.
    target = _corpus(tmp_path, passes=_PASSES, fails=_FAILS, broken=_WILL_NOT_GROUND)

    assert _reported(target).out == _reported(target).out


def test_the_human_format_is_the_default_and_is_also_spellable(tmp_path: Path) -> None:
    # A script that says what it wants must get exactly what it gets by saying nothing, or the
    # explicit spelling is a second format nobody documented.
    target = _corpus(tmp_path, passes=_PASSES, fails=_FAILS)

    implicit = _run(target)
    explicit = _run(target, "--format", "human")

    assert implicit == explicit
    assert "1/2 passed" in implicit.out, "and it is the report on standard output, not a document"


def test_a_format_this_version_does_not_know_is_refused(tmp_path: Path) -> None:
    # The failure a machine consumer would find hardest to notice: asking for a format that does
    # not exist and being handed prose, which parses as nothing and reads as a broken run.
    streams = _run(_corpus(tmp_path, passes=_PASSES), "--format", "sarif")

    assert streams.status == 2
    assert streams.out == "", "an unknown format falls through to no report at all"
    assert "sarif" in streams.err, "and the diagnostic names what was asked for"


def test_a_dry_run_has_no_machine_readable_form_and_says_so(tmp_path: Path) -> None:
    # The dry run narrates a plan rather than producing a report, and this version describes no
    # document for a plan. Refused before anything is discovered: there is no half-run to report.
    streams = _reported(_corpus(tmp_path, passes=_PASSES), "--explain")

    assert streams.status == 2
    assert streams.out == "", "a command line that cannot be run has produced no run to report"
    assert "--explain" in streams.err
    assert "--format json" in streams.err


def test_a_budget_that_is_not_a_positive_finite_number_of_seconds_leaves_no_document(
    tmp_path: Path,
) -> None:
    # Refused the same way and at the same point as the pairing above, and asserted here for the
    # half that belongs to this format: no document at all, rather than a document about a refusal.
    streams = _reported(_corpus(tmp_path, passes=_PASSES), "--budget", "0")

    assert streams.status == 2
    assert streams.out == ""
    assert "--budget" in streams.err


@pytest.mark.parametrize(
    ("described", "prelude", "kind", "expected"),
    [
        ("an allocation that no case owned", _ALLOCATION_FAILS, "resource", 2),
        ("a fault no register anticipated", _NO_REGISTER_ANTICIPATED_THIS, "harness", 3),
    ],
    ids=["out-of-memory", "internal-error"],
)
def test_a_fault_that_reaches_the_console_entry_still_produces_a_document(
    tmp_path: Path, described: str, prelude: str, kind: str, expected: int
) -> None:
    # The register a consumer needs most, because it is the one it cannot infer: handed nothing, it
    # cannot tell a harness that died from a corpus that held no cases. What a backstop writes is a
    # whole document — it names what the run was asked to do, which is why the invocation is
    # settled before the region these handlers guard rather than inside it.
    target = _corpus(tmp_path, passes=_PASSES)

    streams = _reported(target, prelude=prelude)
    document = _document(streams.out)

    assert streams.status == expected, described
    (error,) = document["errors"]
    assert error["kind"] == kind
    assert error["scope"] == "corpus"
    assert error["source"] is None
    assert document["invocation"]["target"] == str(target), (
        "a backstop still says what the run was asked to do"
    )
    assert streams.err, "and the reader is told in prose as well"


def test_a_fault_before_the_run_begins_still_produces_a_document(tmp_path: Path) -> None:
    # The path that decides where the invocation has to be settled. Printing the description is
    # answered before a corpus is looked for, so a fault there reaches the backstop earlier than
    # any run does — and a handler able to name only a run it had already started would have
    # nothing to build a document from.
    target = _corpus(tmp_path, passes=_PASSES)

    streams = _reported(target, "--print-schema", prelude=_DESCRIPTION_IS_NOT_TEXT)
    document = _document(streams.out)

    assert streams.status == 3
    (error,) = document["errors"]
    assert error["is_elenctic_bug"] is True
    assert document["invocation"]["target"] == str(target)
    assert "internal error" in streams.err


def test_printing_the_description_is_not_a_document_and_asks_nothing_of_a_corpus(
    tmp_path: Path,
) -> None:
    # ``--print-schema`` is an action rather than a format: it answers from the package alone, so
    # under either format it writes the description itself, and a target that does not exist never
    # turns the question into a fault.
    streams = _reported(tmp_path / "no_such_directory", "--print-schema")

    assert streams.status == 0
    assert streams.err == ""
    assert _document(streams.out)["title"] == "elenctic run report", "the description, not a report"
