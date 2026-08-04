"""A bound on the whole run, not just on each solve.

``--budget`` bounds one solve. A case can route to several runs, and a corpus has as many cases as
it has files, so the cost of a run is the product of three numbers and only one of them was
bounded. Nothing said how long a run had taken, either, so a corpus that merely timed out
everywhere looked like a slow test suite rather than a run that burned hours.

The deadline is opt-in, and deliberately so: unlike a model cap, there is no run duration that is
obviously unreachable by legitimate use. A default low enough to bound an attack would turn a large
honest corpus into "could not be run", which is a worse failure than the one it prevents.
"""

from pathlib import Path

import pytest

from elenctic import cli
from elenctic.cli import main
from elenctic.outcome import ExitStatus
from support import a_clock_the_deadline_has_already_passed_on

_GOOD = "% @expect sat\n% @count  1\n\na.\n#show a/0.\n"


def _corpus(root: Path, count: int) -> str:
    for index in range(count):
        (root / f"case{index:02d}.lp").write_text(_GOOD, encoding="utf-8")
    return str(root)


def test_a_run_without_a_deadline_is_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main([_corpus(tmp_path, 3)])
    assert status == ExitStatus.OK
    assert "3/3 passed" in capsys.readouterr().out


def test_a_passed_deadline_stops_the_run_and_accounts_for_what_was_not_reached(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The clock says the deadline passed before the first case was reached, so nothing runs. What
    # matters is that the cases that did not run are counted rather than omitted: a summary that
    # explained them by leaving them out would read as a smaller corpus.
    monkeypatch.setattr(cli, "monotonic", a_clock_the_deadline_has_already_passed_on(600.0))
    status = main([_corpus(tmp_path, 3), "--deadline", "600"])
    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT, (
        "an unfinished run is the error register, never a verdict"
    )
    assert "0/3 passed" in captured.out, "the corpus total must still be the corpus total"
    assert "3 could not be run" in captured.out
    assert "deadline" in captured.err.lower()


def test_a_generous_deadline_does_not_interfere(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The other side: a deadline nobody meets must be invisible.
    status = main([_corpus(tmp_path, 3), "--deadline", "600"])
    assert status == ExitStatus.OK
    assert "3/3 passed" in capsys.readouterr().out
