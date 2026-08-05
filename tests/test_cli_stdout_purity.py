"""A region in which standard output carries the report and nothing else.

Under a machine-readable format a single foreign byte makes the document unparseable, and a write
to the descriptor beneath ``sys.stdout`` — which is where a C library reached through a binding may
write — does not pass through anything a Python-side redirect can rebind. Moving the descriptor
itself catches every writer, and what would have landed beside the document is moved rather than
discarded: a reader still sees it, just not where a parser is looking.

Every test here reads the captured file descriptors (``capfd``) or a real subprocess. ``capsys``
cannot see this guarantee at all: it replaces ``sys.stdout`` and leaves the descriptor alone, so it
would report a clean standard output while measuring a stream the region never touches.

The second half of the module is about the case the first half assumes away: a run that has **no
standard error at all**. Moving diagnostics off the document is only possible where there is
somewhere to move them to, and where there is not, every fallback this language offers lands them
on the one stream the document needs to itself. The condition is a closed descriptor, not a
redirected one, and it cannot be reached through anything that starts the process for you.
"""

import contextlib
import errno
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from elenctic.cli import _stdout_to_stderr
from elenctic.outcome import ExitStatus
from support import run_cli_without_standard_error, without_standard_error


def _lowest_free_descriptor() -> int:
    """The number the next descriptor opened in this process will be given.

    POSIX hands out the lowest available number, so this is stable while nothing leaks and rises
    once something does."""
    borrowed = os.dup(1)
    os.close(borrowed)
    return borrowed


class _FlushFailsOnLeaving:
    """A stand-in for ``sys.stdout`` whose second flush fails — the one the region makes on its way
    out, which is what an unwritable standard error does to it."""

    def __init__(self) -> None:
        self.flushes = 0

    def flush(self) -> None:
        self.flushes += 1
        if self.flushes > 1:
            raise OSError("no space left on device")


def test_a_write_past_sys_stdout_does_not_reach_stdout(capfd: pytest.CaptureFixture[str]) -> None:
    with _stdout_to_stderr():
        os.write(1, b"a byte written past sys.stdout\n")
    captured = capfd.readouterr()
    assert captured.out == "", "a descriptor-level write must not reach stdout"
    assert captured.err == "a byte written past sys.stdout\n", "it is shown, not discarded"


def test_the_descriptor_is_restored_after_the_region(capfd: pytest.CaptureFixture[str]) -> None:
    with _stdout_to_stderr():
        pass
    os.write(1, b"the report\n")
    captured = capfd.readouterr()
    assert captured.out == "the report\n", "stdout is the report's again once the region closes"
    assert captured.err == ""


def test_the_descriptor_is_restored_when_the_region_raises(
    capfd: pytest.CaptureFixture[str],
) -> None:
    # A run that ends in a fault still has a report to write, and it is written after the region.
    with pytest.raises(ZeroDivisionError), _stdout_to_stderr():
        raise ZeroDivisionError
    os.write(1, b"the report\n")
    assert capfd.readouterr().out == "the report\n"


def test_the_descriptor_is_restored_when_the_leaving_flush_fails(
    capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The failure that inverts the guarantee: the descriptor is pointed at standard error, so
    # whatever makes standard error unwritable is met by the very flush that has to happen before
    # it can be pointed back. A diversion left in place would send the document to the one stream
    # the region exists to keep it out of.
    before = _lowest_free_descriptor()
    monkeypatch.setattr(sys, "stdout", _FlushFailsOnLeaving())
    with pytest.raises(OSError, match="no space left"), _stdout_to_stderr():
        pass
    monkeypatch.undo()
    os.write(1, b"the report\n")
    assert capfd.readouterr().out == "the report\n", "a failed flush must not keep stdout diverted"
    assert _lowest_free_descriptor() == before, "nor keep the copy of stdout open"


def test_the_saved_descriptor_is_released() -> None:
    before = _lowest_free_descriptor()
    for _ in range(8):
        with _stdout_to_stderr():
            pass
    assert _lowest_free_descriptor() == before, "the copy of stdout is closed, not accumulated"


def test_the_saved_descriptor_is_released_when_the_region_raises() -> None:
    before = _lowest_free_descriptor()
    for _ in range(8):
        with contextlib.suppress(ZeroDivisionError), _stdout_to_stderr():
            raise ZeroDivisionError
    assert _lowest_free_descriptor() == before, "a fault in the region costs no descriptor"


# Held-back output is the precondition both of these need: with nothing pending, a placement
# mistake costs nothing. A pipe block-buffers by default, and the child states the requirement
# rather than relying on that.
_PROLOGUE = """
import sys
from elenctic.cli import _stdout_to_stderr

sys.stdout.reconfigure(line_buffering=False, write_through=False)
sys.stdout.write("pending when the region opens")
"""

_QUIET_REGION = (
    _PROLOGUE
    + """
with _stdout_to_stderr():
    sys.stdout.write("written while the region is open")
"""
)

_RAISING_REGION = (
    _PROLOGUE
    + """
try:
    with _stdout_to_stderr():
        sys.stdout.write("written while the region is open")
        raise ZeroDivisionError
except ZeroDivisionError:
    pass
"""
)


_REPORT_AFTER_REGION = """
import sys
from elenctic.cli import _stdout_to_stderr

with _stdout_to_stderr():
    pass
sys.stdout.write("pending when the region opens")
"""


def _streams_of(child: str) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "-c", child],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == ExitStatus.OK, result.stderr
    return result.stdout, result.stderr


@pytest.mark.parametrize(
    ("child", "how_it_ends"),
    [(_QUIET_REGION, "returning"), (_RAISING_REGION, "raising")],
    ids=["returning", "raising"],
)
def test_the_boundary_flushes_decide_which_stream_holds_what(child: str, how_it_ends: str) -> None:
    # Both flushes are load-bearing, and a buffer is what makes them so: without the first, output
    # written before the region drains into stderr; without the second, output written during it
    # surfaces on stdout beside the document, which is the one thing the region exists to prevent.
    # A region that ends in a fault owes the same placement — that is the case a run has whenever
    # it is going to exit non-zero.
    out, err = _streams_of(child)
    assert out == "pending when the region opens", f"the region ended by {how_it_ends}"
    assert err == "written while the region is open", f"the region ended by {how_it_ends}"


def test_the_stream_is_still_usable_after_the_region() -> None:
    # The document is written through ``sys.stdout`` once the region has closed, so the region owes
    # that stream back open — flushing a stream and closing it are one keystroke apart. Measured out
    # of process on purpose: in process, a closed stream takes the test runner's own capture with
    # it, and a suite that collapses is not the same as an assertion that fails.
    out, err = _streams_of(_REPORT_AFTER_REGION)
    assert out == "pending when the region opens"
    assert err == ""


class _RestoreFails:
    """A stand-in for ``os.dup2`` that fails on the way out of the region.

    Putting the descriptor back is the one step on that path that can fail on its own, and the copy
    taken on the way in is what its failure strands."""

    def __init__(self) -> None:
        # Captured before the stand-in is installed, so calling through does not call the stand-in.
        self._dup2 = os.dup2
        self.calls = 0

    def __call__(self, source: int, target: int) -> int:
        self.calls += 1
        if self.calls == 2:
            raise OSError("the restore could not be made")
        return self._dup2(source, target)


def test_the_copy_of_standard_output_is_released_when_the_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The other half of the pair above. The leaving flush is guarded and the two steps it guards are
    # not, so a restore that fails takes the release with it: a descriptor held for the rest of the
    # process, and another taken every time the region runs again.
    way_back = os.dup(1)
    try:
        before = _lowest_free_descriptor()
        restore = _RestoreFails()
        monkeypatch.setattr(os, "dup2", restore)

        with pytest.raises(OSError, match="the restore could not be made"), _stdout_to_stderr():
            pass

        monkeypatch.undo()
        assert restore.calls == 2, "the region diverts once and restores once — the second is it"
        assert _lowest_free_descriptor() == before, "a restore that failed still owes the copy back"
    finally:
        # This test leaves standard output diverted on purpose, because that is what a failed
        # restore does. Nothing else in the session inherits it.
        os.dup2(way_back, 1)
        os.close(way_back)


# A child that says what its own streams are, run through the same machinery as every measurement
# below it. Written to standard output because there is nowhere else for it to be written.
_REPORTS_ON_ITS_OWN_STREAMS = """
import os
import sys

try:
    os.fstat(2)
    standard_error = "open"
except OSError as bad_descriptor:
    standard_error = f"closed ({bad_descriptor.errno})"
print(f"standard error is {standard_error}, sys.stderr is {sys.stderr!r}")
"""

_PASSES = "% @expect sat\n% @cautious { biscuit }\n\nbiscuit.\n#show biscuit/0.\n"
_FAILS = "% @expect sat\n% @cautious { tea }\n\nbiscuit.\n#show biscuit/0.\n"
_ORPHAN = "% a contract-free file nothing includes.\nhelper(1).\n"

_NO_REGISTER_ANTICIPATED_THIS = """
import elenctic.cli

def _unanticipated(invocation, *, observer=None):
    raise ZeroDivisionError("something no register was written for")

elenctic.cli.run_corpus = _unanticipated
"""


def _corpus(root: Path, **cases: str) -> Path:
    root.mkdir(exist_ok=True)
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return root


def _document(published: str, described: str) -> dict[str, Any]:
    """What standard output carried, parsed — saying what it carried instead when it will not
    parse, since a decode error names a byte position and not the run that wrote it."""
    try:
        parsed: dict[str, Any] = json.loads(published)
    except json.JSONDecodeError as broken:
        raise AssertionError(
            f"{described}: standard output carried no document ({broken}). It held:\n{published}"
        ) from broken
    return parsed


def test_the_instrument_really_takes_standard_error_away() -> None:
    # Every reading below is of a run that has no standard error, and each is worthless if the run
    # had one. Neither obvious way of arranging it works: a wrapper keeps the descriptor open, and
    # so does every value `subprocess` accepts for a stream. What reaches the condition is a shell
    # closing the descriptor and then handing the process over — so that is asserted here, once,
    # rather than assumed by each test that rests on it.
    finished = without_standard_error([sys.executable, "-c", _REPORTS_ON_ITS_OWN_STREAMS])

    assert finished.returncode == 0
    assert finished.stdout == f"standard error is closed ({errno.EBADF}), sys.stderr is None\n", (
        "the condition is a descriptor that is gone, and an interpreter that has noticed"
    )


@pytest.mark.parametrize(
    ("described", "case", "left_with"),
    [
        ("a passing corpus", _PASSES, ExitStatus.OK),
        ("a failing corpus", _FAILS, ExitStatus.NOT_PASSED),
    ],
    ids=["passing", "failing"],
)
def test_the_document_is_alone_on_standard_output_when_there_is_no_standard_error(
    tmp_path: Path, described: str, case: str, left_with: ExitStatus
) -> None:
    # With nowhere to move them to, the diagnostics stay where they were written, and where they
    # were written is the stream the document needs to itself. The passing corpus is the sharper
    # half: the status says nothing went wrong and the consumer holds something that will not parse.
    published, status = run_cli_without_standard_error(
        _corpus(tmp_path, drinks=case), "--format", "json"
    )

    assert _document(published, described)["schema_version"] == 1
    assert status == left_with


def test_the_backstops_own_diagnostic_stays_off_the_documents_stream(tmp_path: Path) -> None:
    # The backstop prints a heading and a traceback beneath it, and it runs *after* the region has
    # closed — so moving the descriptor cannot help it. It is still a diagnostic, and a diagnostic
    # on standard output costs the consumer the whole document rather than a line of it.
    published, status = run_cli_without_standard_error(
        _corpus(tmp_path, drinks=_PASSES),
        "--format",
        "json",
        prelude=_NO_REGISTER_ANTICIPATED_THIS,
    )

    document = _document(published, "a run a fault no register anticipated stopped")
    assert [error["kind"] for error in document["errors"]] == ["harness"]
    assert status == ExitStatus.HARNESS_FAULT


def test_prose_for_a_reader_keeps_its_own_stream_too_with_no_standard_error(
    tmp_path: Path,
) -> None:
    # The format that writes for a person rather than a parser has the same two streams and the same
    # split between them, and a run with no standard error is where the split stops holding by
    # itself. An orphan library is the observation a default run warns about, so it is the one that
    # arrives without asking for `--strict`.
    published, status = run_cli_without_standard_error(
        _corpus(tmp_path, drinks=_PASSES, helper=_ORPHAN)
    )

    assert published == "\n1/1 passed\n", "the report, and nothing that belongs beside it"
    assert status == ExitStatus.OK


def test_a_refused_command_line_leaves_standard_output_empty_with_no_standard_error(
    tmp_path: Path,
) -> None:
    # `--help` states this outright: the reason goes to standard error, standard output stays empty,
    # "so a report is either whole or absent, never half written". A run with no standard error owes
    # the second half of that as much as the first — there is no run to report, so there is nothing
    # for the document's stream to carry.
    published, status = run_cli_without_standard_error(
        _corpus(tmp_path, drinks=_PASSES), "--format", "json", "--budget", "0"
    )

    assert published == "", "a refused command line produced no run, so there is nothing to report"
    assert status == ExitStatus.USER_FAULT
