"""A region in which standard output carries the report and nothing else.

Under a machine-readable format a single foreign byte makes the document unparseable, and a write
to the descriptor beneath ``sys.stdout`` — which is where a C library reached through a binding may
write — does not pass through anything a Python-side redirect can rebind. Moving the descriptor
itself catches every writer, and what would have landed beside the document is moved rather than
discarded: a reader still sees it, just not where a parser is looking.

Every test here reads the captured file descriptors (``capfd``) or a real subprocess. ``capsys``
cannot see this guarantee at all: it replaces ``sys.stdout`` and leaves the descriptor alone, so it
would report a clean standard output while measuring a stream the region never touches.
"""

import contextlib
import os
import subprocess
import sys

import pytest

from elenctic.cli import ExitStatus, _stdout_to_stderr


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
