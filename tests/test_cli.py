"""The ``elenctic`` console entry: exit status separates pass / fail / error, and ``--explain``
narrates the derived run plan without solving."""

from pathlib import Path

import pytest

from elenctic import cli
from elenctic.cli import main
from elenctic.run import RoutingError
from elenctic.run import runs_for as real_runs_for


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_cli_passes_a_satisfied_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")
    status = main([str(tmp_path / "encodings")])
    assert status == 0
    assert "1/1 passed" in capsys.readouterr().out


def test_cli_fails_a_violated_corpus(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # b is shown but never derived, so @cautious { b } FAILs (b ∉ ⋂).
    write(
        tmp_path / "encodings/g/e.lp",
        "a. #show a/0. #show b/0.\n% @expect sat\n% @cautious { b }\n",
    )
    status = main([str(tmp_path / "encodings")])
    assert status == 1
    assert "FAIL" in capsys.readouterr().out


def test_cli_reports_a_corpus_error_with_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @model { a }\n")  # no @expect
    status = main([str(tmp_path / "encodings")])
    assert status == 2
    assert "corpus error" in capsys.readouterr().err


def test_cli_explain_narrates_the_plan_without_solving(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path / "encodings/g/e.lp", "a. #show a/0.\n% @expect sat\n% @cautious { a }\n")
    status = main([str(tmp_path / "encodings"), "--explain"])
    out = capsys.readouterr().out
    assert status == 0
    assert "CAUTIOUS_ALL: @cautious" in out  # the derived run plan, no solve


def test_cli_runs_the_krbook_dogfood_corpus(capsys: pytest.CaptureFixture[str]) -> None:
    # the vendored Gelfond programs pass end-to-end through the real console entry.
    krbook = Path(__file__).parent / "krbook" / "encodings"
    status = main([str(krbook)])
    assert status == 0
    assert "4/4 passed" in capsys.readouterr().out


def test_cli_reports_a_misroute_as_a_harness_error_and_keeps_going(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keystone decision 6: a misroute is a harness error (exit 2), reported distinctly, while the
    # other cases still run. runs_for is correct-by-construction, so inject the failure on one case.
    write(tmp_path / "encodings/good/e.lp", "a. #show a/0.\n% @expect sat\n% @model { a }\n")
    write(tmp_path / "encodings/bad/e.lp", "a. #show a/0.\n% @expect sat\n% @note BOOM\n")

    def selectively_misroute(expectation: object) -> object:
        if "BOOM" in getattr(expectation, "notes", ()):
            raise RoutingError("a stale route")
        return real_runs_for(expectation)  # type: ignore[arg-type]

    monkeypatch.setattr(cli, "runs_for", selectively_misroute)
    status = main([str(tmp_path / "encodings")])
    captured = capsys.readouterr()
    assert status == 2  # a harness error, not a verdict
    assert "HARNESS ERROR" in captured.err and "bad" in captured.err  # the misrouted case named
    assert "1/2 passed" in captured.out  # the good case still ran and passed
    assert "1 harness error" in captured.out
