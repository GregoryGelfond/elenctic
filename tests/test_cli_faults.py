"""What a user sees when a case cannot be run: an error, not a traceback.

An error is not a verdict, so it must not borrow a verdict's exit status, and it must not cost the
run the results of the cases that did complete. These drive the CLI end to end.
"""

from pathlib import Path

import pytest

from elenctic import discovery
from elenctic.cli import main

_GOOD = "% @expect sat\n% @count  2\n\n1 { tea; coffee } 1.\n#show tea/0.\n#show coffee/0.\n"
_UNSAFE = "% @expect sat\n% @count  1\n\nq(1).\np(X) :- q(Y).\n"
_THEORY = "% @elenctic solver clingcon\n% @expect sat\n% @assign { x=1 }\n\n&sum { x } = 1.\n"


def _corpus(root: Path, **cases: str) -> str:
    """Write each named case into ``root`` and return the target to run."""
    for name, text in cases.items():
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return str(root)


def test_an_ungroundable_case_exits_as_an_error_not_a_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = main([_corpus(tmp_path, broken=_UNSAFE)])
    captured = capsys.readouterr()
    # 2 is the error register. 1 would claim the case was tested and decided wrong.
    assert status == 2
    assert "Traceback" not in captured.err
    # The author needs the offending line and the cause, not a summary that grounding stopped.
    assert "unsafe" in captured.err
    assert "broken.lp:5" in captured.err


def test_an_ungroundable_case_does_not_cost_the_other_cases_their_results(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The sharp end of the defect: the run used to abort on the broken case, so the healthy cases'
    # results went with it — including the summary line — and stdout came back empty.
    status = main([_corpus(tmp_path, aaa_good=_GOOD, zzz_broken=_UNSAFE)])
    captured = capsys.readouterr()
    assert status == 2
    assert "passed" in captured.out, "the summary of the cases that ran must survive"
    assert "1/2 passed" in captured.out


def test_a_missing_declared_solver_exits_as_an_error_with_a_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(discovery, "_installed", lambda module: module != "clingcon")
    status = main([_corpus(tmp_path, theory=_THEORY)])
    captured = capsys.readouterr()
    assert status == 2
    assert "Traceback" not in captured.err
    assert 'pip install "elenctic[theory]"' in captured.err
