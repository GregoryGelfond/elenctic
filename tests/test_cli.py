import json
import signal
import sys
from pathlib import Path

import pytest

from elenctic.cli import main
from elenctic.report import Exit
from interrupting import at_first_model

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
    assert run(capsys, tmp_path) == (Exit.CLAIMS_HOLD, "1/1 passed\n")


def test_a_failing_claim_exits_with_the_claim_unmet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "drinks.lp", DRINKS + "% @expect sat\n% @cautious { tea }\n")
    code, out = run(capsys, path)
    assert code == Exit.CLAIM_UNMET
    assert "[FAIL] @cautious { tea } (line 5)" in out


def test_a_missing_file_exits_as_a_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(capsys, tmp_path / "absent.lp")
    assert code == Exit.FAULT
    assert out.splitlines()[0].startswith(f"{tmp_path / 'absent.lp'}:1:1-1: error: ")


def test_json_is_written_on_request(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n")
    code, out = run(capsys, path, "--json")
    assert (code, json.loads(out)["exit_code"]) == (Exit.CLAIMS_HOLD, Exit.CLAIMS_HOLD)


def test_a_search_that_runs_out_of_models_is_undecided_and_exits_with_the_claim_unmet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    code, out = run(capsys, path, "--models", "1")
    assert code == Exit.CLAIM_UNMET
    assert "[UNDECIDED] @count 2" in out


def test_bare_paths_are_the_test_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    assert run(capsys, "test", path) == run(capsys, path)
    assert run(capsys, "--json", path) == run(capsys, "test", "--json", path)


@pytest.mark.parametrize("command", ["repl", "why", "ask", "explain"])
def test_a_reserved_command_says_so_and_exits_as_a_fault(
    command: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([command, "x.lp"]) == Exit.FAULT
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"elenctic: `{command}` is reserved and not yet built\n"


def test_help_names_every_command_and_no_command_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == Exit.CLAIMS_HOLD
    help_text = capsys.readouterr().out
    assert all(name in help_text for name in ("test", "repl", "why", "ask", "explain"))
    with pytest.raises(SystemExit) as usage:
        main([])
    assert usage.value.code == Exit.FAULT


def test_with_no_argument_vector_the_process_arguments_are_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "drinks.lp", DRINKS + "% @expect sat\n")
    monkeypatch.setattr(sys, "argv", ["elenctic", str(path)])
    assert main() == Exit.CLAIMS_HOLD
    assert capsys.readouterr().out == "1/1 passed\n"


FEW_NODES = 40
MANY_NODES = 400
SMALL_BUDGETS = [0.005, 0.02, 0.05]


def path_colouring(nodes: int) -> str:
    return (
        f"node(1..{nodes}). colour(r;g;b). edge(X,X+1) :- node(X), X < {nodes}.\n"
        "1 { assign(X,C) : colour(C) } 1 :- node(X).\n"
        ":- edge(X,Y), assign(X,C), assign(Y,C).\n"
        "#show assign/2.\n% @expect sat\n% @cautious { assign(2,g) }\n"
    )


def test_an_interrupted_consequence_search_is_undecided_and_not_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "path_colouring.lp", path_colouring(FEW_NODES))
    assert run(capsys, path)[0] == Exit.CLAIM_UNMET
    at_first_model(monkeypatch, lambda: signal.raise_signal(signal.SIGINT))
    code, out = run(capsys, path)
    assert code == Exit.CLAIM_UNMET
    assert "[UNDECIDED] @cautious { assign(2,g) } (line 6): search ended: interrupted" in out


@pytest.mark.parametrize("budget", SMALL_BUDGETS)
def test_a_small_budget_never_passes_a_cautious_claim_that_is_false(
    budget: float, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "path_colouring.lp", path_colouring(MANY_NODES))
    code, out = run(capsys, path, "--budget", budget)
    assert code == Exit.CLAIM_UNMET
    assert "1/1 passed" not in out


def test_a_file_that_is_not_utf8_is_an_error_of_the_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "latin1.lp"
    path.write_bytes(b'p("\xff").\n% @expect sat\n')
    code, out = run(capsys, path)
    assert code == Exit.FAULT
    assert (
        out.splitlines()[0] == f"{path}:1:1-1: error: not valid UTF-8: invalid start byte at byte 3"
    )


def test_a_failure_of_its_own_is_an_internal_error_with_a_message_and_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_: object, **__: object) -> None:
        message = "no \x1b[2J"
        raise RecursionError(message)

    monkeypatch.setattr("elenctic.cli.check", broken)
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n")
    code = main([str(path)])
    captured = capsys.readouterr()
    assert code == Exit.INTERNAL_ERROR
    assert captured.out == ""
    assert captured.err == "elenctic: internal error: RecursionError: no \\x1b[2J\n"


REFUSED_LIMIT_TEXTS = [
    ("--models", "a positive integer", value) for value in ["0", "-1", "none", "1.5", ""]
] + [
    ("--budget", "a positive number of seconds", value)
    for value in ["0", "-1", "-0.5", "none", "inf", "nan", ""]
]


@pytest.mark.parametrize(("option", "expected", "value"), REFUSED_LIMIT_TEXTS)
def test_a_limit_is_a_positive_number_or_all(
    option: str, expected: str, value: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n")
    with pytest.raises(SystemExit) as usage:
        main([option, value, str(path)])
    assert usage.value.code == Exit.FAULT
    assert f"{value!r} is not {expected} or `all`" in capsys.readouterr().err


def test_a_limit_may_be_all_or_a_positive_number_even_a_fraction_of_a_second(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    held = (Exit.CLAIMS_HOLD, "1/1 passed\n")
    assert run(capsys, path) == held
    assert run(capsys, path, "--models", "all", "--budget", "all") == held
    assert run(capsys, path, "--models", "2", "--budget", "0.5") == held


ELEMENTS = 4
SUBSETS = 2**ELEMENTS
TOO_SMALL_CAP = SUBSETS - 1


def test_a_search_that_reaches_the_model_cap_is_undecided_unless_the_cap_is_lifted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    every = f"{{ p(1..{ELEMENTS}) }}.\n#show p/1.\n% @expect sat\n% @count {SUBSETS}\n"
    path = write(tmp_path, "subsets.lp", every)
    held = (Exit.CLAIMS_HOLD, "1/1 passed\n")
    assert run(capsys, path) == held
    monkeypatch.setattr("elenctic.cli.DEFAULT_MODEL_CAP", TOO_SMALL_CAP)
    code, out = run(capsys, path)
    assert code == Exit.CLAIM_UNMET
    assert f"[UNDECIDED] @count {SUBSETS}" in out
    assert run(capsys, path, "--models", "all") == held
    assert run(capsys, path, "--models", str(SUBSETS)) == held
