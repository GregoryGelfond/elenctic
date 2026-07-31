"""A resource the run exhausts is reported, not dumped as a traceback.

Grounding is unbounded — clingo's own API offers no clock and no size limit on it — so a program
small enough to write in one line can exhaust memory. clingo raises that as ``MemoryError``, which
is not a ``RuntimeError`` and so was named by no ``except`` clause in the package: it escaped every
register and reached the user as a stack trace, past the bar the rest of the CLI holds to.

Being unable to *bound* the resource does not excuse being unable to *report* it.
"""

from pathlib import Path

import pytest

from elenctic import cli
from elenctic.cli import main

_GOOD = "% @expect sat\n% @count  1\n\na.\n#show a/0.\n"


def test_exhausting_memory_is_reported_as_an_error_not_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Raised where clingo raises it — from the solve path, during a case. A real grounding bomb
    # would take minutes and gigabytes to provoke; the condition under test is what elenctic does
    # when it arrives, not that clingo can be made to produce it.
    (tmp_path / "case.lp").write_text(_GOOD, encoding="utf-8")

    def out_of_memory(*_args: object, **_kwargs: object) -> None:
        raise MemoryError("std::bad_alloc")

    monkeypatch.setattr(cli, "run_case", out_of_memory)
    status = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert status == 2, "an exhausted resource is the error register, never a verdict"
    assert "Traceback" not in captured.err
    assert "memory" in captured.err.lower()


def test_an_unexpected_fault_is_framed_as_an_elenctic_bug(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The complement. Anything not anticipated is elenctic's fault by definition, and saying so is
    # what tells a user it is not their corpus to fix. The traceback is kept — it is the report —
    # but it is introduced rather than dumped.
    (tmp_path / "case.lp").write_text(_GOOD, encoding="utf-8")

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise ZeroDivisionError("an elenctic bug")

    monkeypatch.setattr(cli, "run_case", unexpected)
    status = main([str(tmp_path)])
    captured = capsys.readouterr()
    assert status == 2
    assert "elenctic" in captured.err.lower(), "the user must be told whose fault this is"
    assert "ZeroDivisionError" in captured.err, "the cause is still reported, not swallowed"
