import json
import sys
from pathlib import Path

import pytest

from elenctic.cli import main

DRINKS = "1 { tea; coffee } 1.\nbiscuit.\n#show tea/0. #show coffee/0. #show biscuit/0.\n"


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text)
    return path


def run(capsys: pytest.CaptureFixture[str], *argv: object) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    return code, capsys.readouterr().out


def test_a_directory_is_searched_for_cases_and_libraries_are_left_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "drinks.lp", DRINKS + "% @expect sat\n% @count 2\n")
    write(tmp_path, "library.lp", "helper(1).\n")
    assert run(capsys, tmp_path) == (0, "1/1 passed\n")


def test_a_failing_claim_exits_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "drinks.lp", DRINKS + "% @expect sat\n% @cautious { tea }\n")
    code, out = run(capsys, path)
    assert code == 1
    assert "[FAIL] @cautious { tea } (line 5)" in out


def test_a_missing_file_exits_two(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(capsys, tmp_path / "absent.lp")
    assert code == 2
    assert out.splitlines()[0].startswith(f"{tmp_path / 'absent.lp'}:1:1-1: error: ")


def test_json_is_written_on_request(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n")
    code, out = run(capsys, path, "--json")
    assert (code, json.loads(out)["exit_code"]) == (0, 0)


def test_a_search_that_runs_out_of_models_is_undecided_and_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    code, out = run(capsys, path, "--models", "1")
    assert code == 1
    assert "[UNDECIDED] @count 2" in out


def test_a_budget_of_zero_is_no_budget(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    assert run(capsys, path, "--budget", 0) == (0, "1/1 passed\n")


def test_bare_paths_are_the_test_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    assert run(capsys, "test", path) == run(capsys, path)
    assert run(capsys, "--json", path) == run(capsys, "test", "--json", path)


@pytest.mark.parametrize("command", ["repl", "why", "ask", "explain"])
def test_a_reserved_command_says_so_and_exits_two(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command, "x.lp"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"elenctic: `{command}` is reserved and not yet built\n"


def test_help_names_every_command_and_no_command_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    help_text = capsys.readouterr().out
    assert all(name in help_text for name in ("test", "repl", "why", "ask", "explain"))
    with pytest.raises(SystemExit) as usage:
        main([])
    assert usage.value.code == 2


def test_with_no_argument_vector_the_process_arguments_are_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "drinks.lp", DRINKS + "% @expect sat\n")
    monkeypatch.setattr(sys, "argv", ["elenctic", str(path)])
    assert main() == 0
    assert capsys.readouterr().out == "1/1 passed\n"
