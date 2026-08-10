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

The child is asked to confirm which copy of the package it loaded before it runs anything. An
instrument that measures a different installation than the one under test reports on code nobody
changed, and says nothing while doing it.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from elenctic.json_report import SCHEMA_VERSION, dumps, schema_text
from elenctic.outcome import ExitStatus
from support import Streams, child_environment, cli_help_text, document_of, run_cli

_PASSES = (
    "% @elenctic solver clingo\n% @expect sat\n% @count 2\n\n"
    "1 { tea; coffee } 1.\n#show tea/0.\n#show coffee/0.\n"
)
# `tea` is declared observable, so the claim is one elenctic can read and therefore decide; the
# choice rule is what makes it FALSE, since `tea` then holds in one answer set and not the other.
# Undeclared it would be refused rather than failed, and this corpus needs a failure.
_FAILS = "% @expect sat\n% @cautious { tea }\n\nbiscuit. { tea }.\n#show biscuit/0.\n#show tea/0.\n"
_WILL_NOT_GROUND = "% @expect sat\n% @count 1\n\nq(1).\np(X) :- q(Y).\n"
_ORPHAN = "% a contract-free file nothing includes.\nhelper(1).\n"
_DECLARES_THE_THEORY_SOLVER = (
    "% @elenctic solver clingcon\n% @expect sat\n% @assign { x=1 }\n\n&sum { x } = 1.\n"
)
# Three derived runs, so the order the checks come back in is neither alphabetical nor its own
# reverse — which is what makes an order assertion over it able to notice either.
_FOUR_CLAIMS = (
    "% @elenctic solver clingo\n% @expect sat\n% @count 2\n"
    "% @cautious { biscuit }\n% @brave { tea }\n\n"
    "1 { tea; coffee } 1.\nbiscuit.\n#show tea/0.\n#show coffee/0.\n#show biscuit/0.\n"
)
_OPTIMAL_CONSEQUENCES = (
    "% @elenctic solver clingo\n% @expect sat\n"
    "% @cautious optimal { a }\n% @brave optimal { a }\n\n"
    "{ a; b }.\n#minimize { 1,b : b }.\n#show a/0.\n#show b/0.\n"
)

# An environment whose standard output cannot encode the report. Reproducing it takes saying so
# three times, because this interpreter works hard not to be left in it — which is why the defect
# it exposes is easy to ship and hard to meet by accident.
_STDOUT_CANNOT_ENCODE = {"LC_ALL": "C", "PYTHONCOERCECLOCALE": "0", "PYTHONUTF8": "0"}

_ALLOCATION_FAILS = """
import elenctic.cli

def _out_of_memory(invocation, *, observer=None):
    raise MemoryError

elenctic.cli.run_corpus = _out_of_memory
"""

_NO_REGISTER_ANTICIPATED_THIS = """
import elenctic.cli

def _unanticipated(invocation, *, observer=None):
    raise ZeroDivisionError("something no register was written for")

elenctic.cli.run_corpus = _unanticipated
"""

# A writer beneath the Python stream, which is what the whole redirect exists for: the grounder is a
# C library reached through a binding, and it writes to the descriptor rather than to the object
# this language calls standard output. Nothing in the pipeline does this today — both solver
# controls install a Python logger — so without standing one here on purpose, the difference between
# moving the descriptor and rebinding the stream is invisible.
_WRITES_BENEATH_THE_PYTHON_STREAM = """
import os
import elenctic.cli

_ran = elenctic.cli.run_corpus

def _noisy(invocation, *, observer=None):
    os.write(1, b"a byte written past sys.stdout\\n")
    outcome = _ran(invocation, observer=observer)
    os.write(1, b"and another once the run is done\\n")
    return outcome

elenctic.cli.run_corpus = _noisy
"""

# A fault in printing the description that is none of the ones the handler names — not the file
# being absent or in the way, not its bytes failing to decode, not its text failing to parse, and
# not the allocation. So it passes the handler naming a mis-shaped environment and reaches the
# backstop instead, before a corpus has been looked at, which is what a fault nobody anticipated
# should do: a reader told to reinstall a package that is fine has been sent to fix the wrong thing.
#
# Stubs rather than contrived files because that is the point — the mechanisms a real damaged file
# produces are all caught now, and these hold the arm for the ones that are not.
#
# **Two of them, and the second is not a duplicate.** One of the families the handler names is
# `JSONDecodeError`, which *is* a `ValueError` — so a `ValueError` that is not one of those is the
# case that proves the named tuple does not swallow its own supertype, and it is the obvious fault
# to reach for. It is also the one fault a backstop narrowed from `Exception` to `ValueError` would
# still catch: measured, that narrowing changed nothing any test could see. A resource loader that
# is not the filesystem raises whatever it raises, so the second stands outside that hierarchy
# entirely, and the two together are what make the width of the catch load-bearing.
_DESCRIPTION_IS_NOT_TEXT = """
import elenctic.cli

def _unreadable():
    raise ValueError("the packaged description is not valid text")

elenctic.cli.schema_text = _unreadable
"""

_DESCRIPTION_LOADER_MISBEHAVES = """
import elenctic.cli

def _unreadable():
    raise RuntimeError("the loader this package was installed under gave up")

elenctic.cli.schema_text = _unreadable
"""


def _corpus(root: Path, **cases: str) -> Path:
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return root


def _reported(
    target: Path,
    *flags: str,
    prelude: str = "",
    env: dict[str, str] | None = None,
    hash_seed: str | None = None,
) -> Streams:
    return run_cli(
        target, "--format", "json", *flags, prelude=prelude, env=env, hash_seed=hash_seed
    )


def _described(*, prelude: str = "", env: dict[str, str] | None = None) -> Streams:
    """One invocation of the command that writes the description of the report.

    No target and no format, because that command has neither: it is answered from the installed
    package, so there is nothing about a corpus for it to be told and nothing about a run for it to
    choose. Passing either would be measuring a usage error rather than the description.
    """
    return run_cli(None, command="schema", prelude=prelude, env=env)


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
    document = document_of(streams)

    assert streams.out == dumps(document), (
        "standard output is exactly the document, rendered as the package renders it — no prose "
        "before it, nothing appended, and one trailing newline"
    )
    assert document["summary"] == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "undecided": 0,
        "errors": 0,
        # The orphan library, and the one case that declared no solver — the other declares one.
        "hygiene": 2,
    }
    assert streams.status == ExitStatus.NOT_PASSED, (
        "a case decided wrong, and nothing else went wrong"
    )
    assert "FAIL" in streams.err, "the human report is moved to standard error, not discarded"
    assert "1/2 passed" in streams.err, "including the summary the run writes at the end"


def test_a_write_beneath_the_python_stream_never_reaches_the_document(tmp_path: Path) -> None:
    # The guarantee the redirect exists for, and the only test that can tell it apart from
    # rebinding this language's standard output: a writer that goes to the descriptor directly, as
    # the grounder does, inside a real run. Rebinding would let both of these land beside the
    # document and leave it unparseable.
    target = _corpus(tmp_path, passes=_PASSES)

    streams = _reported(target, prelude=_WRITES_BENEATH_THE_PYTHON_STREAM)

    assert streams.out == dumps(document_of(streams)), "a byte written past the stream is not here"
    assert "a byte written past sys.stdout" in streams.err, "it is shown, not discarded"
    assert "and another once the run is done" in streams.err, (
        "including one written after the run returned, since the region covers the whole of it"
    )
    assert streams.status == ExitStatus.OK


@pytest.mark.parametrize(
    ("described", "cases", "flags", "prelude"),
    [
        ("a run where every case passed", {"passes": _PASSES}, (), ""),
        (
            "a run with every register populated",
            {"fails": _FAILS, "broken": _WILL_NOT_GROUND},
            (),
            "",
        ),
        ("a target that does not exist", {}, (), ""),
        (
            "a run graded under --strict",
            {"passes": _PASSES, "orphan_library": _ORPHAN},
            ("--strict",),
            "",
        ),
        ("a fault that reached the console entry", {"passes": _PASSES}, (), _ALLOCATION_FAILS),
        ("an elenctic bug that reached it", {"passes": _PASSES}, (), _NO_REGISTER_ANTICIPATED_THIS),
    ],
    ids=["passing", "every-register", "no-corpus", "strict", "backstop", "harness-bug"],
)
def test_every_document_the_command_line_emits_is_one_the_published_description_accepts(
    tmp_path: Path, described: str, cases: dict[str, str], flags: tuple[str, ...], prelude: str
) -> None:
    # The description is validated against documents built in process elsewhere; this validates the
    # ones a consumer actually receives. Without it the closed field space is a promise about a
    # function rather than about the stream, and a field added on the way out — or a whole register
    # a backstop writes and nothing else does — is described by nothing.
    target = _corpus(tmp_path, **cases) if cases else tmp_path / "no_such_directory"

    streams = _reported(target, *flags, prelude=prelude)

    errors = sorted(
        Draft202012Validator(json.loads(schema_text())).iter_errors(document_of(streams)),
        key=lambda error: list(error.absolute_path),
    )
    assert not errors, f"{described}: " + "; ".join(
        f"{list(error.absolute_path)}: {error.message}" for error in errors
    )


@pytest.mark.parametrize(
    ("described", "cases", "flags", "prelude", "expected"),
    [
        ("a corpus where every case passes", {"passes": _PASSES}, (), "", 0),
        ("a case that decided wrong", {"fails": _FAILS}, (), "", 1),
        ("a case that could not be run", {"broken": _WILL_NOT_GROUND}, (), "", 2),
        (
            "an observation this run graded an error",
            {"passes": _PASSES, "orphan_library": _ORPHAN},
            ("--strict",),
            "",
            2,
        ),
        (
            "a fault elenctic must answer for",
            {"passes": _PASSES},
            (),
            _NO_REGISTER_ANTICIPATED_THIS,
            3,
        ),
    ],
    ids=["passing", "failing", "unrunnable", "strict-hygiene", "elenctic-bug"],
)
def test_the_status_a_consumer_reads_off_the_document_is_the_status_the_process_returned(
    tmp_path: Path,
    described: str,
    cases: dict[str, str],
    flags: tuple[str, ...],
    prelude: str,
    expected: int,
) -> None:
    # A stored report outlives the process that produced it, so the document promises its own
    # grading ladder — all four rungs of it, the topmost included, which is the one that outranks
    # every other and so the one a consumer can least afford to reconstruct wrongly.
    streams = _reported(_corpus(tmp_path, **cases), *flags, prelude=prelude)

    assert streams.status == expected, described
    assert _status_off_the_document(document_of(streams)) == streams.status, described


def test_a_corpus_that_could_not_be_discovered_still_produces_a_document(tmp_path: Path) -> None:
    # Nothing ran, so there is no verdict to report — but a consumer handed nothing at all cannot
    # tell a corpus that could not be found from a run that died before writing anything.
    streams = _reported(tmp_path / "no_such_directory")
    document = document_of(streams)

    assert streams.status == ExitStatus.USER_FAULT
    assert document["cases"] == [], "nothing was tested, so nothing belongs in that register"
    (error,) = document["errors"]
    assert error["scope"] == "corpus", "the fault belongs to no single case"
    assert error["is_elenctic_bug"] is False
    assert document["summary"]["total"] == 0
    # The two formats of one run, checked against each other rather than each against itself. What
    # the reader is told the fault was and what the consumer is told it was are the same word, so a
    # reader moving between a terminal and a document is not made to keep a table between them.
    assert f"{error['kind']} error: " in streams.err


def test_a_case_that_will_not_ground_costs_only_its_own_verdict(tmp_path: Path) -> None:
    target = _corpus(tmp_path, passes=_PASSES, broken=_WILL_NOT_GROUND)

    streams = _reported(target)
    document = document_of(streams)

    assert streams.status == ExitStatus.USER_FAULT
    (case,) = document["cases"]
    assert case["verdict"] == "pass", "a broken sibling costs a case nothing"
    assert case["source"].endswith("passes.lp")
    assert case["solver"] == "clingo"
    # Each claim against the line it was written on. Asserted as a mapping rather than as a list,
    # because the order of this array is the run's own and the document promises only that it is
    # stable — pinning a particular order here would make a legitimate change to how runs are
    # derived look like a broken contract.
    assert {check["tag"]: check["line"] for check in case["checks"]} == {
        "@expect sat": 2,
        "@count": 3,
    }
    assert all(check["status"] == "pass" for check in case["checks"])
    (error,) = document["errors"]
    assert error["kind"] == "program", "the program under test is broken, not elenctic"
    assert error["scope"] == "case"
    assert error["source"].endswith("broken.lp")
    assert document["summary"]["total"] == 2, "both files were discovered, and both are accounted"


def test_hygiene_this_run_graded_an_error_reaches_the_document(tmp_path: Path) -> None:
    target = _corpus(tmp_path, fails=_FAILS, orphan_library=_ORPHAN)

    streams = _reported(target, "--strict")
    document = document_of(streams)

    assert streams.status == ExitStatus.USER_FAULT, (
        "the gate fails on a corpus-health observation under --strict"
    )
    graded = {record["kind"]: record for record in document["hygiene"]}
    assert sorted(graded) == ["orphan_library", "undeclared_solver"]
    assert graded["orphan_library"]["grade"] == "error"
    assert graded["undeclared_solver"]["grade"] == "error", (
        "--strict grades the otherwise-silent observation too, which is what it is for"
    )
    assert graded["orphan_library"]["source"].endswith("orphan_library.lp")
    assert graded["orphan_library"]["message"], "an observation whose reason was dropped is not one"


def test_an_observation_this_run_stayed_quiet_about_is_still_recorded(tmp_path: Path) -> None:
    # Without --strict an undeclared solver is graded silent: recorded, and deliberately not shown.
    # A consumer applying its own policy is owed the fact, which it cannot have if a run that chose
    # to say nothing about it also chose to drop it.
    target = _corpus(tmp_path, fails=_FAILS)

    streams = _reported(target)
    document = document_of(streams)

    (observation,) = document["hygiene"]
    assert observation["kind"] == "undeclared_solver"
    assert observation["grade"] == "silent"
    assert document["summary"]["hygiene"] == 1, "the count includes what was never reported"
    assert "undeclared solver" not in streams.err, "and the run said nothing about it"


def test_the_same_corpus_serializes_identically_twice(tmp_path: Path) -> None:
    # No case here is bounded by time, so nothing in the document depends on how fast the machine
    # is. A consumer diffing two reports of an unchanged corpus must see no diff — and the two seeds
    # are named here rather than left to the environment, because two runs under one seed would
    # compare a hash-ordered document against itself and see nothing.
    target = _corpus(tmp_path, passes=_PASSES, fails=_FAILS, broken=_WILL_NOT_GROUND)

    first = _reported(target, hash_seed="0")
    second = _reported(target, hash_seed="1")

    assert first.status == ExitStatus.USER_FAULT, (
        "and the runs behind the comparison actually happened"
    )
    assert document_of(first)["summary"]["total"] == 3
    assert first.out == second.out


def test_the_human_format_is_the_default_and_is_also_spellable(tmp_path: Path) -> None:
    # A script that says what it wants must get exactly what it gets by saying nothing, or the
    # explicit spelling is a second format nobody documented.
    target = _corpus(tmp_path, passes=_PASSES, fails=_FAILS)

    implicit = run_cli(target)
    explicit = run_cli(target, "--format", "human")

    assert implicit == explicit
    assert "1/2 passed" in implicit.out, "and it is the report on standard output, not a document"


def test_the_human_format_writes_no_document_even_when_the_run_dies(tmp_path: Path) -> None:
    # The backstops write a document because a machine consumer asked for one. A reader who did not
    # ask gets prose and a status, and never a document dumped after the traceback.
    target = _corpus(tmp_path, passes=_PASSES)

    streams = run_cli(target, prelude=_NO_REGISTER_ANTICIPATED_THIS)

    assert streams.status == ExitStatus.HARNESS_FAULT
    assert streams.out == "", "nothing was asked for on this stream, so nothing is put there"
    assert "harness error: " in streams.err, "the locus the record was filed under, not the frame"


def test_a_format_this_version_does_not_know_is_refused(tmp_path: Path) -> None:
    # The failure a machine consumer would find hardest to notice: asking for a format that does
    # not exist and being handed prose, which parses as nothing and reads as a broken run.
    streams = run_cli(_corpus(tmp_path, passes=_PASSES), "--format", "sarif")

    assert streams.status == ExitStatus.USER_FAULT
    assert streams.out == "", "an unknown format falls through to no report at all"
    assert "sarif" in streams.err, "and the diagnostic names what was asked for"


def test_a_dry_run_has_no_machine_readable_form_and_says_so(tmp_path: Path) -> None:
    # The dry run narrates a plan rather than producing a report, and this version describes no
    # document for a plan. It used to be a pairing of two flags that each made sense alone, refused
    # in a paragraph of elenctic's own; now the format is one of `run`'s options and there is no
    # such pairing to type. What is kept is that nothing is published either way — and the *reason*,
    # which the paragraph was carrying and which the parser's terser refusal does not say, is
    # asserted below to be somewhere a reader meets before typing it rather than after.
    streams = run_cli(_corpus(tmp_path, passes=_PASSES), "--format", "json", command="explain")

    assert streams.status == ExitStatus.USER_FAULT
    assert streams.out == "", "a command line that cannot be run has produced no run to report"
    assert "--format json" in streams.err, "and the refusal names what was asked for"


def test_the_dry_run_says_where_its_missing_machine_readable_form_went() -> None:
    # The knowledge the removed paragraph carried, kept where a reader meets it *before* typing the
    # flag. Held here rather than left to the prose, because prose nothing reads is exactly how the
    # sentence would come to be dropped in a later edit — and then the reader who asks argparse for
    # `--format` on a plan is told only that it is unrecognized.
    said = " ".join(cli_help_text("explain").split())

    assert "no machine-readable form for a plan" in said, "why there is no --format here"
    assert "`run`" in said, "and where the format that does exist belongs"


def test_a_budget_that_is_not_a_positive_finite_number_of_seconds_leaves_no_document(
    tmp_path: Path,
) -> None:
    # Refused the same way and at the same point as the pairing above, and asserted here for the
    # half that belongs to this format: no document at all, rather than a document about a refusal.
    streams = _reported(_corpus(tmp_path, passes=_PASSES), "--budget", "0")

    assert streams.status == ExitStatus.USER_FAULT
    assert streams.out == ""
    assert "--budget" in streams.err


def test_what_the_command_line_asked_for_is_what_the_document_says_was_asked_for(
    tmp_path: Path,
) -> None:
    # The provenance a stored report needs in order to be reproduced. Every one of these is a value
    # the command line supplied, so a document that carried a default instead would describe a run
    # nobody made — and the two dials would be decorative without anything saying so.
    target = _corpus(tmp_path, passes=_PASSES)

    streams = _reported(target, "--budget", "7.5", "--deadline", "900", "--strict")

    assert document_of(streams)["invocation"] == {
        "target": str(target),
        "strict": True,
        "budget": 7.5,
        "deadline": 900.0,
    }


def test_a_run_given_no_deadline_says_so_rather_than_inventing_one(tmp_path: Path) -> None:
    streams = _reported(_corpus(tmp_path, passes=_PASSES))

    assert document_of(streams)["invocation"]["deadline"] is None


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
    document = document_of(streams)

    assert streams.status == expected, described
    (error,) = document["errors"]
    assert error["kind"] == kind
    assert error["scope"] == "corpus"
    assert error["source"] is None
    assert error["message"], "an error whose reason was dropped is not a report"
    assert document["cases"] == []
    assert document["invocation"]["target"] == str(target), (
        "a backstop still says what the run was asked to do"
    )


def test_an_allocation_failure_with_no_case_to_name_says_so_in_the_record(tmp_path: Path) -> None:
    # The wording is not the one used against a single case, and the difference is the whole reason
    # there are two: a frame that cannot say which case was running cannot offer the remedy that
    # names one, so it asks for the corpus to be bounded instead. A record carrying the other
    # sentence would tell a reader to reduce a case nobody can identify.
    streams = _reported(_corpus(tmp_path, passes=_PASSES), prelude=_ALLOCATION_FAILS)

    (error,) = document_of(streams)["errors"]
    assert "this corpus" in error["message"]
    assert "this case" not in error["message"]
    assert "resource error: " in streams.err, "and the reader is told in prose as well"


@pytest.mark.parametrize(
    "prelude",
    [_DESCRIPTION_IS_NOT_TEXT, _DESCRIPTION_LOADER_MISBEHAVES],
    ids=["a value error that is not one of the named ones", "a family the handler never heard of"],
)
def test_a_fault_while_printing_the_description_produces_no_document(prelude: str) -> None:
    # A document reports a run, and the description asks for none — so a fault there is reported as
    # prose and a status, the same way its readable-environment sibling already is. A run report
    # here would describe a corpus that was never looked at, and it was one conjunct in `main` that
    # kept it from being written: with `--print-schema --format json` and the conjunct deleted, a
    # 529-byte document claiming `"target": "tests"` and `"total": 0` was published under a status
    # that says elenctic is broken.
    #
    # That state can no longer be typed — this command has no format to be asked for, which
    # `test_cli_help` holds by asserting it offers no dial at all — so what is left to measure is
    # the end of it: a fault here publishes nothing, whichever frame meets it.
    streams = _described(prelude=prelude)

    assert streams.status == ExitStatus.HARNESS_FAULT
    assert streams.out == ""
    assert "harness error: " in streams.err, "the locus the record was filed under, not the frame"


def _installed_with_the_description(root: Path, text: str) -> str:
    """A prelude that stands a package whose packaged description is ``text`` in front of the child.

    The file is written for real, at the size asked for, and the child reads it by the same lookup
    the shipped one is read by; what the prelude arranges is *which directory* the package was
    installed into. That is the half of a packaging accident a test cannot reproduce by damaging the
    copy the suite is running out of.
    """
    packaged = root / "schema" / f"output-v{SCHEMA_VERSION}.schema.json"
    packaged.parent.mkdir(parents=True, exist_ok=True)
    packaged.write_text(text, encoding="utf-8")
    return (
        "import elenctic.json_report\nfrom pathlib import Path\n"
        f"elenctic.json_report.files = lambda _package: Path({str(root)!r})\n"
    )


@pytest.mark.parametrize(("damage", "kept"), [("dropped to nothing", 0), ("cut off part-way", 100)])
def test_a_damaged_description_is_reported_rather_than_published(
    damage: str, kept: int, tmp_path: Path
) -> None:
    # The zero-byte end of this is the one that reads as success: writing nothing to standard output
    # succeeds, so a reader who redirected it into a file gets an empty file, status 0, and not a
    # word anywhere saying their installation is broken. The truncated end publishes half a document
    # under the same status, which a consumer meets as a parse error naming their own decoder.
    #
    # Both are the accident the absent-file diagnostic already exists for, so they are told in its
    # sentence rather than in one of their own.
    prelude = _installed_with_the_description(tmp_path, schema_text()[:kept])

    streams = _described(prelude=prelude)

    assert streams.status == ExitStatus.USER_FAULT
    assert streams.out == "", "half a description, or none of one, is not a description to publish"
    assert "environment error: " in streams.err, "the environment is mis-shaped, not elenctic wrong"


def _installed_with_a_directory_where_the_description_goes(root: Path) -> str:
    """A prelude whose packaged description is present, intact, and not readable.

    A directory rather than a mode change, deliberately: ``chmod 000`` is not a condition a process
    running as root can be put into, so a suite that used one would report a pass on the machines
    least likely to have been thought about. This raises the same ``OSError`` the handler catches,
    for every user.
    """
    packaged = root / "schema" / f"output-v{SCHEMA_VERSION}.schema.json"
    packaged.mkdir(parents=True, exist_ok=True)
    return (
        "import elenctic.json_report\nfrom pathlib import Path\n"
        f"elenctic.json_report.files = lambda _package: Path({str(root)!r})\n"
    )


def test_a_description_that_cannot_be_read_says_which_of_the_reasons_it_was(tmp_path: Path) -> None:
    # Present and unreadable is not the same accident as absent, and their remedies differ: one is
    # fixed by reinstalling and one is fixed by the file's own permissions or by whatever put a
    # directory there. Nothing in the sentence could tell them apart, so it told everybody the
    # packaging answer — and told the reader who can *see* the file sitting there that their copy
    # has "the code and not the data".
    prelude = _installed_with_a_directory_where_the_description_goes(tmp_path)

    streams = _described(prelude=prelude)

    assert streams.status == ExitStatus.USER_FAULT
    assert streams.out == ""
    assert str(tmp_path) in streams.err, "the reason the read gave, which is what separates them"
    assert "rather than anything you configured" not in streams.err, (
        "a mode or a directory in the way IS something the reader configured"
    )


def test_the_reason_a_description_could_not_be_read_is_shown_safely(tmp_path: Path) -> None:
    # The reason is a string from outside this program, and it goes to a terminal — so it is
    # sanitized like every other such string in the report.
    #
    # **The input has to be chosen carefully, and the obvious one does not test this.** The fault
    # the *operating system* raises carries its filename through `repr`, which escapes it already —
    # so a test installing the package under a directory whose name holds an escape passes whether
    # or not this program sanitizes anything, and measures CPython's `repr`. A one-argument
    # `OSError` is the shape that reaches `str` unescaped, and a resource loader that is not the
    # filesystem — a zip importer, a vendored backend — raises exactly that.
    erases_the_line = "\x1b[2K"
    prelude = (
        "import elenctic.cli\n"
        "def _unreadable():\n"
        f"    raise OSError('a loader that could not read it{erases_the_line}')\n"
        "elenctic.cli.schema_text = _unreadable\n"
    )

    streams = _described(prelude=prelude)

    assert streams.status == ExitStatus.USER_FAULT
    assert erases_the_line not in streams.err, "the escape reached the reader's terminal intact"
    assert "\\x1b[2K" in streams.err, "and nothing was silently dropped instead"


def test_running_out_of_memory_printing_the_description_does_not_blame_a_corpus(
    tmp_path: Path,
) -> None:
    # The description is answered from the package alone: no target is walked, nothing is
    # grounded, and no case runs. The allocation backstop it shared with a run told such a reader to
    # "reduce what it grounds and enumerates" — the same overreach the cut-short report sentence was
    # rewritten for, one arm over.
    prelude = "import json\njson.loads = _hungry\n".replace(
        "_hungry", "lambda *a, **k: (_ for _ in ()).throw(MemoryError())"
    )

    streams = _described(prelude=prelude)

    assert streams.out == "", "nothing is published when the description could not be held"
    assert "resource error: " in streams.err, "still the allocation failure it is, not a bug report"
    assert "running this corpus" not in streams.err, "no corpus was run"
    assert "reduce what it grounds and enumerates" not in streams.err, (
        "the remedy offered was for a run that did not happen"
    )
    assert "no corpus was looked at and nothing was grounded" in streams.err, (
        "and the reader is told which of the two kinds of allocation failure this was"
    )


def test_running_out_of_memory_writing_the_description_does_not_blame_a_corpus_either() -> None:
    # The sibling of the test above, on the other side of the one statement that separates them.
    # Reading the packaged description was answered by the sentence about a description; *writing*
    # it fell out of that frame and was met by the run's backstop, which told a reader who ran no
    # corpus to reduce what theirs grounds. The two messages exist in order to be told apart, and
    # nothing held the boundary between them — the failure was one statement past the guard.
    prelude = (
        "import elenctic.cli\n"
        "def _out_of_memory(_document):\n"
        "    raise MemoryError\n"
        "elenctic.cli.publish = _out_of_memory\n"
    )

    streams = _described(prelude=prelude)

    assert streams.out == "", "nothing is published when the description could not be written"
    assert "resource error: " in streams.err, "still the allocation failure it is, not a bug report"
    assert "running this corpus" not in streams.err, "no corpus was run"
    assert "reduce what it grounds and enumerates" not in streams.err, (
        "the remedy offered was for a run that did not happen"
    )
    assert "no corpus was looked at and nothing was grounded" in streams.err, (
        "and the reader is told which of the two kinds of allocation failure this was"
    )


def test_the_description_is_what_this_command_writes_and_it_asks_nothing_of_a_corpus() -> None:
    # An action rather than a format, which is now what the grammar says rather than what its help
    # said: there is no format here to choose and no target to walk, so the one thing this command
    # can write is the description, and nothing about a corpus can turn the question into a fault.
    streams = _described()

    assert streams.status == ExitStatus.OK
    assert streams.err == ""
    assert document_of(streams)["title"] == "elenctic run report", "the description, not a report"


def test_the_description_takes_no_target(tmp_path: Path) -> None:
    # It is answered from the installed package, so a target could only ever be accepted and
    # ignored — which is what it was, with the help saying so in a sentence. A reader who names
    # their corpus here believes they are being told about *it*; now they are told they are not,
    # instead of being handed something unrelated with the status that says nothing went wrong.
    streams = run_cli(_corpus(tmp_path, passes=_PASSES), command="schema")

    assert streams.status == ExitStatus.USER_FAULT
    assert streams.out == "", "and nothing is published to be mistaken for a description of it"
    assert "unrecognized" in streams.err


def test_the_document_is_utf8_whatever_the_environment_would_have_chosen(tmp_path: Path) -> None:
    # JSON is UTF-8 by its own specification, so the encoding of the report belongs to the report.
    # Written through this language's text layer it would be encoded in whatever the environment
    # picked, and on a machine whose standard output is ASCII that does not write the report at all
    # — it raises, on a character the report is entitled to contain.
    target = _corpus(tmp_path, passes=_PASSES)

    streams = _reported(target, env=_STDOUT_CANNOT_ENCODE)
    document = document_of(streams)

    assert streams.status == ExitStatus.OK
    (case,) = document["cases"]
    messages = " ".join(check["message"] for check in case["checks"])
    assert not messages.isascii(), (
        "the corpus behind this test must produce a document that needs it"
    )
    assert streams.out == dumps(document)


def test_the_description_is_utf8_whatever_the_environment_would_have_chosen(tmp_path: Path) -> None:
    streams = _described(env=_STDOUT_CANNOT_ENCODE)

    assert streams.status == ExitStatus.OK
    assert streams.out == schema_text()
    assert not streams.out.isascii(), "the description is what makes this test say anything"


def test_each_run_is_given_the_hash_seed_it_was_asked_for(tmp_path: Path) -> None:
    # The instrument behind the check above, asserted rather than believed. Clearing the seed is
    # what makes an unasked-for run pick its own; setting it is what lets two runs be given two.
    # Inheriting the parent's would make every "two runs" comparison one run against itself.
    assert child_environment(hash_seed="0")["PYTHONHASHSEED"] == "0"
    assert child_environment(hash_seed="1")["PYTHONHASHSEED"] == "1"
    assert "PYTHONHASHSEED" not in child_environment()


def test_a_case_is_named_by_the_path_a_reader_would_open(tmp_path: Path) -> None:
    # The whole of the path, not its last segment. An editor placing a diagnostic opens this
    # string, and a bare file name is one it cannot resolve — while every assertion that only
    # checks the ending would go on passing.
    target = _corpus(tmp_path, passes=_PASSES)

    (case,) = document_of(_reported(target))["cases"]

    assert case["source"] == str(target / "passes.lp")


def test_a_case_says_which_solver_actually_ran_it(tmp_path: Path) -> None:
    # Two cases declaring two solvers, so the field has to carry the case's own answer rather than
    # the one this version happens to default to.
    target = _corpus(tmp_path, plain=_PASSES, theory=_DECLARES_THE_THEORY_SOLVER)

    document = document_of(_reported(target))

    assert {case["source"].split("/")[-1]: case["solver"] for case in document["cases"]} == {
        "plain.lp": "clingo",
        "theory.lp": "clingcon",
    }


def test_a_run_that_was_not_strict_says_it_was_not(tmp_path: Path) -> None:
    # The dial's other footing. Asserted because every other assertion about it is against a run
    # that passed --strict, so a document hardcoding "strict": true would tell every reader of
    # every ordinary stored report that the run had been a gate.
    streams = _reported(_corpus(tmp_path, passes=_PASSES))

    assert document_of(streams)["invocation"]["strict"] is False


def test_a_cases_checks_come_back_in_the_order_the_run_derived_them(tmp_path: Path) -> None:
    # Nothing is sorted: the order is the run's own, and a check's position in the array is its
    # identity within the document. This contract derives three runs, so the order it produces is
    # neither alphabetical nor its own reverse — which is what lets this notice either.
    target = _corpus(tmp_path, menu=_FOUR_CLAIMS)

    (case,) = document_of(_reported(target))["cases"]

    assert [check["tag"] for check in case["checks"]] == [
        "@count",
        "@expect sat",
        "@cautious",
        "@brave",
    ]


def test_a_repeatable_tag_on_an_optimal_base_still_says_which_claim_it_judged(
    tmp_path: Path,
) -> None:
    # The published description promises a subject for all four consequence tags, and the two
    # optimal-base ones are the pair nothing else observes — so two `@brave optimal` lines could
    # become indistinguishable in the document while the description went on promising otherwise.
    target = _corpus(tmp_path, opt=_OPTIMAL_CONSEQUENCES)

    (case,) = document_of(_reported(target))["cases"]

    subjects = {check["tag"]: check["subject"] for check in case["checks"]}
    assert subjects["@cautious optimal"] == "{ a }"
    assert subjects["@brave optimal"] == "{ a }"
