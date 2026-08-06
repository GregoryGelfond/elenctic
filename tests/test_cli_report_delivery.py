"""What a run does when nothing is reading standard output.

A reader that stops — ``| head``, a pager quit, a consumer that found what it came for — leaves
every further write with nowhere to land. That is not a fault in the corpus and not a bug in
elenctic, and it is the one event where saying so plainly is the whole of the job: the verdict the
run reached is unaffected by how its output was piped, and a status claiming otherwise fails a CI
job for the plumbing around it.

There is one event here and it can be met at two moments — while the report is being written, or
when what is still held in the stream is emptied on the way out — and the reader is owed the same
answer either way. Which of the two a given run meets is decided by how much the stream happens to
hold, which is the language's business and not this project's, so the moment is arranged here
rather than reached by writing more than some number of bytes.

Most tests here run elenctic as a process whose standard output is a pipe with the read end already
closed. In process there is nothing to measure: the stream a test runner installs takes every byte,
and a run whose output is being read cannot meet this at all. The last two are the neighbours that
must not be answered the same way — a stream that failed for its own reasons, and a process started
with no standard output at all.
"""

import io
import os
import sys
from contextlib import redirect_stdout, suppress
from pathlib import Path

import pytest

from elenctic.cli import _NOWHERE_TO_PUBLISH, _hand_over_standard_output, main
from elenctic.outcome import ExitStatus
from support import (
    run_cli,
    run_cli_with_neither_stream_reachable,
    run_cli_with_nobody_reading,
    run_cli_with_nobody_reading_diagnostics,
    run_cli_without_standard_output,
)

_PASSES = "% @expect sat\n% @cautious { biscuit }\n\nbiscuit.\n#show biscuit/0.\n"
_FAILS = "% @expect sat\n% @cautious { tea }\n\nbiscuit.\n#show biscuit/0.\n"
_ORPHAN = "% a contract-free file nothing includes.\nhelper(1).\n"

# Standard output given a buffer too small to hold what the run writes, so the write that fails is
# one the run makes rather than the one the interpreter makes on its way out. Stated as a condition
# rather than reached by writing a great deal: how much a stream holds before it writes through is a
# number this language owns and has already changed once, and a corpus sized against yesterday's
# value stops reaching this at all, silently, while still passing. The bound it needs from the
# other side is that what a run writes exceeds 512 bytes: a one-case document runs to about
# fourteen hundred and the packaged description to twenty thousand, so the margin is wide, but
# an artefact that ever shrank past it would turn this arm into a copy of the one below.
_A_SMALL_BUFFER = """
import io

sys.stdout = io.TextIOWrapper(
    io.BufferedWriter(io.FileIO(1, "wb", closefd=False), buffer_size=512), encoding="utf-8"
)
"""

# And a third condition, which neither of the two below reaches: standard output writing through on
# every write rather than holding anything, which is what `PYTHONUNBUFFERED=1` makes it and what an
# ordinary CI image sets. The buffers above are sized against the *artefacts* — a document of about
# fourteen hundred bytes, a description of twenty thousand — and the run's own tally is a dozen, so
# under either of them the tally is still held when the stream is emptied and the write that fails
# is the hand-over's. Only here does the tally's own write reach the descriptor.
_WRITES_THROUGH = """
import io

sys.stdout = io.TextIOWrapper(
    io.FileIO(1, "wb", closefd=False), encoding="utf-8", write_through=True
)
"""

# And the other moment, arranged the same way: a buffer far larger than anything written through it,
# so nothing reaches the descriptor until the region empties the stream on the way out. Both halves
# have to be stated. Left to the default, "still held" would rest on each artefact happening to be
# smaller than whatever this language holds back today — an unwritten bound, on a number that has
# already moved once, and the day it moves again this arm silently becomes a copy of the one above.
# Four mebibytes against a description of about twenty kilobytes is the margin, said out loud.
_A_LARGE_BUFFER = """
import io

sys.stdout = io.TextIOWrapper(
    io.BufferedWriter(io.FileIO(1, "wb", closefd=False), buffer_size=4 * 1024 * 1024),
    encoding="utf-8",
)
"""

# Pinned verbatim rather than imported, so that changing what a reader is told is a deliberate act
# and not a side effect of editing the frame it is printed from. Every clause has to hold on every
# path below, and the description of the report's shape is the one that catches an overreach: it is
# answered from the package alone, so nothing there ran a corpus or reached a verdict.
_CUT_SHORT = (
    "output cut short: nothing is reading standard output, so what reached the other end is "
    "incomplete. Losing the reader affected nothing else — this leaves with the status it would "
    "have left with anyway. Whoever needs the whole of it should read to the end, or write it to a "
    "file and read the file."
)


def _corpus(root: Path, **cases: str) -> Path:
    root.mkdir(exist_ok=True)
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("described", "case", "flags", "prelude", "left_with"),
    [
        (
            "the document, written through",
            _PASSES,
            ("--format", "json"),
            _A_SMALL_BUFFER,
            ExitStatus.OK,
        ),
        ("the document, still held", _PASSES, ("--format", "json"), _A_LARGE_BUFFER, ExitStatus.OK),
        ("prose, written as the run goes", _FAILS, (), _A_LARGE_BUFFER, ExitStatus.NOT_PASSED),
        # The row this table was missing, and the one the human format actually meets in CI:
        # every prose row held "the stream keeps what it is given" fixed, so the tally — the
        # one standard-output write made outside the frame that answers for standard output —
        # was never reached. `PYTHONUNBUFFERED=1` in an ordinary CI image is what makes it.
        ("prose, written through", _FAILS, (), _WRITES_THROUGH, ExitStatus.NOT_PASSED),
        (
            "a plan, written without solving",
            _PASSES,
            ("--explain",),
            _A_LARGE_BUFFER,
            ExitStatus.OK,
        ),
        (
            "the description, written through",
            _PASSES,
            ("--print-schema",),
            _A_SMALL_BUFFER,
            ExitStatus.OK,
        ),
        (
            "the description, still held",
            _PASSES,
            ("--print-schema",),
            _A_LARGE_BUFFER,
            ExitStatus.OK,
        ),
    ],
    ids=[
        "document-written",
        "document-held",
        "prose",
        "prose-written-through",
        "explain",
        "description-written",
        "description-held",
    ],
)
def test_a_reader_that_stopped_leaves_the_run_with_its_own_status(
    tmp_path: Path,
    described: str,
    case: str,
    flags: tuple[str, ...],
    prelude: str,
    left_with: ExitStatus,
) -> None:
    # One event, one answer. Without it the status is whichever accident got there first: the write
    # that failed inside the run reads as a case decided wrong, the same write in the description's
    # path reads as a bug in elenctic, and the emptying the interpreter does after this frame has
    # returned leaves with a number the ladder does not publish at all.
    said, status = run_cli_with_nobody_reading(
        _corpus(tmp_path, drinks=case), *flags, prelude=prelude
    )

    assert status == left_with, f"{described}: a reader that stopped is not a verdict"
    # The last line, and said out loud rather than indexed into: an empty stream would otherwise
    # fail with an IndexError about a list, which names neither the run nor what it did not say.
    assert said.splitlines()[-1:] == [_CUT_SHORT], f"{described}: said {said!r}"


@pytest.mark.parametrize(
    ("described", "flags", "prelude"),
    [
        ("written through", ("--format", "json"), _A_SMALL_BUFFER),
        ("still held", ("--format", "json"), _A_LARGE_BUFFER),
        # The claim is about what a reader is handed, and the human path hands them the most: the
        # rows above were both machine-readable, so the format that prints for the length of a run
        # was outside a guarantee whose name does not qualify itself.
        ("prose, written through", (), _WRITES_THROUGH),
        ("prose, still held", (), _A_LARGE_BUFFER),
    ],
    ids=["written", "held", "prose-written", "prose-held"],
)
def test_a_reader_that_stopped_is_reported_as_a_sentence_and_never_as_a_traceback(
    tmp_path: Path, described: str, flags: tuple[str, ...], prelude: str
) -> None:
    # Every user-visible fault in this project is a sentence a reader can act on. Both of the ways
    # this used to arrive were the opposite: a raw traceback with elenctic's own frames in it, and
    # the interpreter's note about an exception it had already given up on.
    said, _ = run_cli_with_nobody_reading(
        _corpus(tmp_path, drinks=_PASSES), *flags, prelude=prelude
    )

    assert "Traceback" not in said, f"{described}: the reader is handed elenctic's own frames"
    assert "Exception ignored" not in said, f"{described}: the interpreter answered after we did"


# A standard output that will not take the bytes for a reason that has nothing to do with a reader:
# no space left, a device that failed. It is the other way the write in the region can fail, and the
# one this program has no answer for — the remedy is not "read all of it", and the fault is not
# elenctic's either.
_THE_STREAM_CANNOT_TAKE_IT = """
import io


class _Full(io.TextIOWrapper):
    def flush(self):
        raise OSError(28, "No space left on device")


sys.stdout = _Full(io.BufferedWriter(io.FileIO(1, "wb", closefd=False)), encoding="utf-8")
"""


def test_a_stream_that_failed_is_not_answered_as_a_reader_that_stopped(tmp_path: Path) -> None:
    # The region empties the stream, so every way emptying it can fail now passes through one frame.
    # Only one of them is a reader, and the other two answers on offer are both wrong: the sentence
    # about reading all of it names a remedy that would not help, and the backstop one frame up
    # tells someone whose disk is full that they have found a bug in this program.
    streams = run_cli(_corpus(tmp_path, drinks=_FAILS), prelude=_THE_STREAM_CANNOT_TAKE_IT)

    # A positive first, and it is the fixture's own words rather than the interpreter's: what the
    # stream said went wrong still reaches the reader. Two absences alone would also be satisfied by
    # a child that said nothing at all, including one that died before it ran.
    assert "No space left" in streams.err, "what the stream reported still reaches the reader"
    assert streams.status != ExitStatus.HARNESS_FAULT, "a full disk is not a fault in elenctic"
    assert _CUT_SHORT not in streams.err, "and no reader stopped — this is a stream that failed"


def test_saying_the_report_was_cut_short_can_meet_the_same_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `2>&1 | head` is an ordinary way to read a long report, and it puts the sentence about the
    # lost reader on the very stream that was lost. The frame whose whole job is to answer a reader
    # who has gone cannot itself die of one: left to raise, it reaches the backstop above it and a
    # piped run is told it has found a bug in elenctic. In process, because what is being watched is
    # the frame rather than a run, and out of process the two streams are one dead pipe with nothing
    # readable on the far side to assert against.
    read_end, write_end = os.pipe()
    os.close(read_end)
    unread = os.fdopen(write_end, "w", buffering=1)
    try:
        monkeypatch.setattr(sys, "stdout", unread)
        monkeypatch.setattr(sys, "stderr", unread)
        unread.write("a report nobody is reading")

        _hand_over_standard_output()

        # Not "nothing raised". That much also holds if the pipe was never broken, or if the frame
        # returned before it reached the arm at all, and a test that cannot tell its subject from
        # its own scaffolding failing to arrange the condition measures nothing. The arm's last act
        # is to point the stream it could not write to at the null device, and only that arm does
        # it — so this says the whole answer ran, including the half that could not be delivered.
        nowhere = os.open(os.devnull, os.O_WRONLY)
        try:
            assert os.path.sameopenfile(unread.fileno(), nowhere), (
                "the broken-pipe answer ran to its end"
            )
        finally:
            os.close(nowhere)
        # And the stream it repointed is this one, not descriptor 1 — which is why this test needs
        # no way back. Reaching for the usual number instead would leave a caller who had moved
        # standard output elsewhere with a descriptor they were still using pointed at nothing.
    finally:
        monkeypatch.undo()
        with suppress(OSError):
            unread.close()


def test_a_broken_standard_error_does_not_take_a_healthy_report_with_it(tmp_path: Path) -> None:
    # The tail of a run writes to both streams — the tally to standard output, the hygiene summary
    # to standard error — so a broken pipe met while it runs can be about either. Answering it as a
    # fact about standard output points a *healthy* standard output at the null device, and a
    # reader keeping the report in a file is handed an empty one. `--strict` is what makes the tail
    # write to standard error at all, and the orphan library is what it writes about.
    corpus = _corpus(tmp_path / "corpus", drinks=_PASSES, orphan=_ORPHAN)
    report = tmp_path / "report.txt"

    kept, _ = run_cli_with_nobody_reading_diagnostics(corpus, "--strict", report=report)

    # The status is not the subject here and is left to the interpreter, which still meets the
    # diagnostics it could not write when it empties standard error on the way out.
    assert kept == "\n1/1 passed\n", "the report is its reader's, and standard error is not it"


def test_a_caller_who_captured_standard_output_needs_no_byte_layer(tmp_path: Path) -> None:
    # The obvious way to embed this: call `main` with standard output redirected into a stream of
    # your own. A text stream is what `redirect_stdout` is for and what this project's own help
    # capture uses, and it has no byte layer beneath it — so a hand-over that reaches for one turns
    # the plainest embedding there is into a fault reported against elenctic. Only an artefact that
    # has to carry its own encoding needs those bytes, and a run that wrote its report as it went is
    # not carrying one.
    captured = io.StringIO()

    with redirect_stdout(captured):
        status = main([str(_corpus(tmp_path / "corpus", drinks=_PASSES))])

    assert status == ExitStatus.OK
    assert captured.getvalue() == "\n1/1 passed\n", "and the caller has the report"


def test_neither_stream_reachable_still_leaves_with_the_run_s_own_status(tmp_path: Path) -> None:
    # The two conditions this seam answers, met together: the diagnostics have nowhere to go *and*
    # the report has no reader. The sentence about the lost reader goes to the null device with
    # everything else, which is what closing standard error asked for — so the status is the whole
    # of what a consumer has left, and it has to be the one the corpus earned. Pinned because it is
    # the composition of two separately-correct answers, and a composition nobody wrote down is one
    # nobody decided.
    passed = run_cli_with_neither_stream_reachable(
        _corpus(tmp_path / "passing", drinks=_PASSES), "--format", "json"
    )
    failed = run_cli_with_neither_stream_reachable(
        _corpus(tmp_path / "failing", drinks=_FAILS), "--format", "json"
    )

    assert (passed, failed) == (ExitStatus.OK, ExitStatus.NOT_PASSED)


def test_a_run_given_no_standard_output_at_all_is_not_a_fault(tmp_path: Path) -> None:
    # A stream that is gone rather than unread. This language leaves `sys.stdout` unbuilt, `print`
    # then writes nowhere without complaining, and nothing is held anywhere to be handed over — so
    # the frame that empties standard output has to notice there is none. Reaching for it costs the
    # run its status and tells someone who asked for silence that they have found a bug.
    said, status = run_cli_without_standard_output(_corpus(tmp_path, drinks=_PASSES))

    assert status == ExitStatus.OK, "a corpus that passes still passes with nowhere to say so"
    assert said == "", f"and it says nothing: {said!r}"


@pytest.mark.parametrize(
    ("described", "flags"),
    [("the document", ("--format", "json")), ("the description", ("--print-schema",))],
    ids=["document", "description"],
)
def test_asking_for_an_artefact_with_nowhere_to_put_it_is_refused(
    tmp_path: Path, described: str, flags: tuple[str, ...]
) -> None:
    # The companion to the row above, and the distinction is the point: prose is a courtesy, so a
    # run with nobody to narrate to still runs and still earns its status. An artefact is the
    # deliverable, so asking for one with no stream to write it to is a contradiction — and met
    # mid-run rather than refused, both of these told a reader they had found a bug in elenctic,
    # over a stream that reader had closed on purpose.
    said, status = run_cli_without_standard_output(_corpus(tmp_path, drinks=_PASSES), *flags)

    assert status == ExitStatus.USER_FAULT, f"{described}: their own doing, and theirs to undo"
    assert "usage error: " in said, f"{described}: refused before anything is looked at"
    assert "elenctic bug" not in said, f"{described}: and never filed against elenctic"
    # The sentence itself, verbatim, for the reason _CUT_SHORT is pinned above: the message
    # *is* the behaviour of a refusal, and every assertion here short of it is satisfied by
    # any refusal at all — including one about flags this reader never passed.
    assert _NOWHERE_TO_PUBLISH in said, f"{described}: and says which thing has nowhere to go"


# A standard *error* that will not take the bytes for a reason that has nothing to do with a reader.
# The tail writes its two diagnostics there, ahead of the tally, so this is the other way that write
# can fail — and the one every fixture here would otherwise miss, since a pipe with no reader is
# always EPIPE.
_DIAGNOSTICS_CANNOT_BE_WRITTEN = """
import io


class _Full(io.TextIOWrapper):
    def write(self, text):
        raise OSError(28, "No space left on device")


sys.stderr = _Full(io.BufferedWriter(io.FileIO(2, "wb", closefd=False)), encoding="utf-8")
"""


def test_a_standard_error_that_fails_for_its_own_reasons_keeps_the_report(tmp_path: Path) -> None:
    # A diagnostic that cannot be delivered does not stop the report being delivered, and that has
    # to hold for every way the stream can refuse it — not only for the lost reader every other
    # fixture here arranges. Narrowed to that one errno, a full disk on standard error takes a
    # healthy standard output's report with it and is filed against elenctic.
    corpus = _corpus(tmp_path / "corpus", drinks=_PASSES, orphan=_ORPHAN)
    streams = run_cli(corpus, "--strict", prelude=_DIAGNOSTICS_CANNOT_BE_WRITTEN)

    assert "1/1 passed" in streams.out, "the report is its reader's"
    assert streams.status == ExitStatus.USER_FAULT, "and --strict still fails the run"
    assert "elenctic bug" not in streams.out


def test_the_run_still_reaches_its_verdict_with_nobody_reading(tmp_path: Path) -> None:
    # The corpus is what the status is about, and a broken pipe says nothing about a corpus. A
    # failing one still fails and a passing one still passes, whatever happened to the report.
    failed = _corpus(tmp_path / "failing", drinks=_FAILS)
    passed = _corpus(tmp_path / "passing", drinks=_PASSES)

    failing, refuted = run_cli_with_nobody_reading(failed, "--format", "json")
    passing, held = run_cli_with_nobody_reading(passed, "--format", "json")

    assert "0/1 passed" in failing, f"the run's own tally is still written: {failing!r}"
    assert "1/1 passed" in passing, f"the run's own tally is still written: {passing!r}"
    assert (refuted, held) == (ExitStatus.NOT_PASSED, ExitStatus.OK), "and its own verdict is kept"
