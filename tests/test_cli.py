import json
import shlex
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import Link
from elenctic import check as real_check
from elenctic.cli import main
from elenctic.determination import Truncation, option
from elenctic.inquiry import AskExit, WhyExit, ask
from elenctic.patterns import Pattern
from elenctic.program import Program
from elenctic.query import Answered, stream
from elenctic.report import Exit
from elenctic.terms import Variable
from interrupting import at_first_answer_set

DRINKS = "1 { tea; coffee } 1.\nbiscuit.\n#show tea/0. #show coffee/0. #show biscuit/0.\n"


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text)
    return path


def run(capsys: pytest.CaptureFixture[str], *argv: object) -> tuple[int, str]:
    code = main([str(a) for a in argv])
    return code, capsys.readouterr().out


def run_both(capsys: pytest.CaptureFixture[str], *argv: object) -> tuple[int, str, str]:
    code = main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


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
    code, out, err = run_both(capsys, tmp_path / "absent.lp")
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: cannot read `{tmp_path / 'absent.lp'}`"
    assert out == "0/1 passed, 1 error\n"


def test_json_is_written_on_request(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n")
    code, out = run(capsys, path, "--json")
    assert (code, json.loads(out)["exit_code"]) == (Exit.CLAIMS_HOLD, Exit.CLAIMS_HOLD)


def test_a_search_that_runs_out_of_answer_sets_is_undecided_and_exits_with_the_claim_unmet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    code, out = run(capsys, path, "--max-answer-sets", "1")
    assert code == Exit.CLAIM_UNMET
    assert "[UNDECIDED] @count 2" in out


def test_bare_paths_are_the_test_command(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    assert run(capsys, "test", path) == run(capsys, path)
    assert run(capsys, "--json", path) == run(capsys, "test", "--json", path)


@pytest.mark.parametrize("command", ["repl"])
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
SMALL_TIME_LIMITS = [0.005, 0.02, 0.05]


def path_coloring(nodes: int) -> str:
    return (
        f"node(1..{nodes}). color(r;g;b). edge(X,X+1) :- node(X), X < {nodes}.\n"
        "1 { assign(X,C) : color(C) } 1 :- node(X).\n"
        ":- edge(X,Y), assign(X,C), assign(Y,C).\n"
        "#show assign/2.\n% @expect sat\n% @cautious { assign(2,g) }\n"
    )


def test_an_interrupted_consequence_search_is_undecided_and_not_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "path_coloring.lp", path_coloring(FEW_NODES))
    assert run(capsys, path)[0] == Exit.CLAIM_UNMET
    at_first_answer_set(monkeypatch, lambda: signal.raise_signal(signal.SIGINT))
    code, out = run(capsys, path)
    assert code == Exit.CLAIM_UNMET
    assert "[UNDECIDED] @cautious { assign(2,g) } (line 6): search ended: interrupted" in out


@pytest.mark.parametrize("seconds", SMALL_TIME_LIMITS)
def test_a_small_time_limit_never_passes_a_cautious_claim_that_is_false(
    seconds: float, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "path_coloring.lp", path_coloring(MANY_NODES))
    code, out = run(capsys, path, "--max-seconds", seconds)
    assert code == Exit.CLAIM_UNMET
    assert "1/1 passed" not in out


def test_a_file_that_is_not_utf8_is_an_error_of_the_request(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "latin1.lp"
    path.write_bytes(b'p("\xff").\n% @expect sat\n')
    code, out, err = run_both(capsys, path)
    assert code == Exit.FAULT
    assert "error: cannot read" in err
    assert "not valid UTF-8 at byte 3" in err
    assert out == "0/1 passed, 1 error\n"


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
    assert captured.out == "0/1 passed, 1 error\n"
    assert captured.err == "elenctic: internal error: RecursionError: no \\x1b[2J\n"


REFUSED_LIMIT_TEXTS = [
    ("--max-answer-sets", "a positive integer", value) for value in ["0", "-1", "none", "1.5", ""]
] + [
    ("--max-seconds", "a positive number of seconds", value)
    for value in ["0", "-1", "-0.5", "none", "inf", "nan", ""]
]


def test_an_internal_error_in_one_source_leaves_the_others(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def selective(program: object, **kw: object) -> object:
        assert isinstance(program, Program)
        if Path(program.source).name == "b.lp":
            message = "injected failure in one source"
            raise RuntimeError(message)
        return real_check(program, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr("elenctic.cli.check", selective)
    a = write(tmp_path, "a.lp", "p.\n% @expect sat\n% @count 3\n")
    b = write(tmp_path, "b.lp", "p.\n% @expect sat\n")
    c = write(tmp_path, "c.lp", "p.\n% @expect sat\n")
    code = main([str(a), str(b), str(c)])
    captured = capsys.readouterr()
    assert code == Exit.INTERNAL_ERROR
    assert "a.lp" in captured.out
    assert "FAIL" in captured.out
    assert "1/3 passed, 1 fail, 1 error" in captured.out
    assert "elenctic: internal error: RuntimeError: injected failure in one source" in captured.err


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
    assert run(capsys, path, "--max-answer-sets", "all", "--max-seconds", "all") == held
    assert run(capsys, path, "--max-answer-sets", "2", "--max-seconds", "0.5") == held


ELEMENTS = 4
SUBSETS = 2**ELEMENTS
TOO_SMALL_LIMIT = SUBSETS - 1


def test_a_search_that_reaches_the_answer_set_limit_is_undecided_unless_the_limit_is_lifted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    every = f"{{ p(1..{ELEMENTS}) }}.\n#show p/1.\n% @expect sat\n% @count {SUBSETS}\n"
    path = write(tmp_path, "subsets.lp", every)
    held = (Exit.CLAIMS_HOLD, "1/1 passed\n")
    assert run(capsys, path) == held
    monkeypatch.setattr("elenctic.cli.DEFAULT_MAX_ANSWER_SETS", TOO_SMALL_LIMIT)
    code, out = run(capsys, path)
    assert code == Exit.CLAIM_UNMET
    assert f"[UNDECIDED] @count {SUBSETS}" in out
    assert run(capsys, path, "--max-answer-sets", "all") == held
    assert run(capsys, path, "--max-answer-sets", str(SUBSETS)) == held


@pytest.mark.parametrize("cut", [Truncation.MAX_ANSWER_SETS, Truncation.MAX_SECONDS])
def test_the_option_a_search_ended_message_names_is_one_the_command_takes(
    cut: Truncation, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        main(["test", "--help"])
    assert option(cut) in capsys.readouterr().out


def test_a_search_that_reaches_the_answer_set_limit_names_the_option_that_set_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @query yes { tea }\n")
    code, out = run(capsys, path, "--max-answer-sets", "1")
    assert code == Exit.CLAIM_UNMET
    assert "search ended: answer-set limit reached (--max-answer-sets)" in out


def test_python_m_elenctic_runs_the_same_cli() -> None:
    help_main = subprocess.run(
        [sys.executable, "-m", "elenctic", "--help"], check=False, capture_output=True, text=True
    )
    assert help_main.returncode == 0
    assert "usage: elenctic" in help_main.stdout
    version = subprocess.run(
        [sys.executable, "-m", "elenctic", "-V"], check=False, capture_output=True, text=True
    )
    assert version.returncode == 0
    assert version.stdout.startswith("elenctic ")


def test_a_tuple_valued_one_variable_binding_is_not_flattened(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`{ (1,2) }` for p(X) must FAIL when the answer sets are p(1) and p(2)."""
    path = write(
        tmp_path,
        "flat.lp",
        "p(1). p(2).\n#show p/1.\n% @expect sat\n% @query yes { p(X) } = { (1,2) }\n",
    )
    code, out = run(capsys, "--color", "never", "-v", path)
    assert code == Exit.CLAIM_UNMET
    assert "[FAIL]" in out


def test_a_nested_tuple_in_an_n_ary_binding_is_accepted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(
        tmp_path,
        "nested.lp",
        "p((1,2),3).\n#show p/2.\n% @expect sat\n% @query yes { p(X,Y) } = { ((1,2),3) }\n",
    )
    code, out = run(capsys, "--color", "never", path)
    assert code == Exit.CLAIMS_HOLD
    assert "1/1 passed" in out


def test_a_named_file_without_a_contract_is_a_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "lib.lp", "a.\n")
    code, out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert f"error: `{path}` carries no contract tag\n" in err
    assert "help: a contract-free `.lp` is a library; name a case, or walk a directory" in err
    assert "1 error" in out


def test_a_named_file_with_a_bom_is_a_loud_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "bom.lp"
    path.write_bytes("\ufeff% @expect sat\na.\n".encode("utf-8"))
    code, _out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert "byte order mark" in err or "BOM" in err


def test_a_walked_near_miss_is_a_note_and_does_not_fail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "ok.lp", "a.\n% @expect sat\n")
    write(tmp_path, "miss.lp", "{a}.\n% @expct sat\n% @cout 3\n")
    code, out, err = run_both(capsys, "--color", "never", tmp_path)
    assert code == Exit.CLAIMS_HOLD
    assert "1/1 passed" in out
    assert "miss.lp" in err
    assert "@expct" in err or "expct" in err


def test_a_walked_library_without_near_miss_is_silent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "ok.lp", "a.\n% @expect sat\n")
    write(tmp_path, "lib.lp", "helper(1).\n")
    code, out, err = run_both(capsys, "--color", "never", tmp_path)
    assert code == Exit.CLAIMS_HOLD
    assert err == ""
    assert "1/1 passed" in out


def test_count_over_hidden_variation_uses_shown_projection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`@count` reads distinct shown sets; hidden atoms must not inflate the census."""
    path = write(
        tmp_path,
        "projection.lp",
        "{ h(1..17) }.\na.\n#show a/0.\n% @expect sat\n% @count 1\n",
    )
    code, out = run(capsys, "--color", "never", "-v", path)
    assert code == Exit.CLAIMS_HOLD
    assert "[PASS] @count 1" in out


def test_absent_answer_set_fails_under_shown_projection(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(
        tmp_path,
        "absent.lp",
        "{ h(1..17) }.\na.\nb :- not a.\n#show a/0.\n#show b/0.\n"
        "% @expect sat\n% @answer-set { b }\n",
    )
    code, out = run(capsys, "--color", "never", "-v", path)
    assert code == Exit.CLAIM_UNMET
    assert "[FAIL] @answer-set { b }" in out


def test_a_spanless_fault_names_its_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "ok.lp", "a.\n% @expect sat\n")
    write(tmp_path, "bad.lp", "a.\n% @count 1\n")  # missing @expect
    code, _out, err = run_both(capsys, "--color", "never", tmp_path)
    assert code == Exit.FAULT
    assert "bad.lp" in err
    code, _out, err = run_both(capsys, "--color", "never", "--short", tmp_path)
    assert code == Exit.FAULT
    assert "bad.lp" in err


def test_a_script_without_runtime_support_names_the_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(
        tmp_path,
        "script.lp",
        "#script (python)\ndef f():\n    return 1\n#end.\na.\n% @expect sat\n",
    )
    code, _out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert "python support not available" in err


def test_an_include_fault_points_at_the_included_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "lib.lp", "q.\n% lib line 2\np(X) :- q.\n")
    path = write(
        tmp_path,
        "main.lp",
        '#include "lib.lp".\n% @expect sat\n% main line 3 -- not the faulty line\n',
    )
    code, _out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert "lib.lp:3:" in err
    assert "p(X) :- q." in err
    assert "main line 3" not in err


def test_an_undecided_truncated_claim_has_an_ended_detail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(
        tmp_path,
        "trunc.lp",
        "{ p(1..17) }.\n#show p/1.\n% @expect sat\n% @count 131072\n",
    )
    code, out = run(capsys, "--json", "--max-answer-sets", "50", path)
    assert code == Exit.CLAIM_UNMET
    document = json.loads(out)
    findings = document["run"]["entries"][0]["result"]["findings"]
    undecided = next(f for f in findings if f["verdict"] == "undecided")
    assert undecided["detail"]["kind"] == "ended"


def test_json_carries_verdict_and_solver_without_program_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", "p.\n% @expect sat\n")
    code, out = run(capsys, "--json", path)
    assert code == Exit.CLAIMS_HOLD
    document = json.loads(out)
    entry = document["run"]["entries"][0]
    assert "text" not in entry
    assert entry["result"]["verdict"] == "pass"
    assert entry["result"]["solver"] == "clingo"


def test_an_include_outside_the_root_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = write(tmp_path, "outside.lp", "secret(42).\n")
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    case = f'#include "{outside}".\n% @expect sat\n% @cautious {{ secret(41) }}\n'
    write(corpus, "case.lp", case)
    code, out, err = run_both(capsys, corpus)
    assert code == Exit.FAULT
    assert f"which is outside the root {corpus}" in err
    assert (
        "help: test from a directory that holds every included file, or name one as the root "
        "(`--root` on the command line, `root=` to `check`)"
    ) in err
    assert "secret(42)" not in err
    assert "secret(42)" not in out


def test_an_include_under_the_root_is_allowed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "lib.lp", "p.\n")
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    write(deep, "case.lp", '#include "../../lib.lp".\n% @expect sat\n')
    assert run(capsys, tmp_path) == (Exit.CLAIMS_HOLD, "1/1 passed\n")


def sibling_layout(tmp_path: Path) -> Path:
    """Lay out a case under `scenarios/` that includes a library under `encodings/`."""
    (tmp_path / "encodings").mkdir()
    write(tmp_path / "encodings", "lib.lp", "p.\n")
    scenario = tmp_path / "scenarios" / "one"
    scenario.mkdir(parents=True)
    write(scenario, "case.lp", '#include "../../encodings/lib.lp".\n% @expect sat\n')
    return scenario


def test_root_lets_a_subtree_include_from_a_sibling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = sibling_layout(tmp_path)
    assert run(capsys, "--root", tmp_path, tmp_path / "scenarios") == (
        Exit.CLAIMS_HOLD,
        "1/1 passed\n",
    )
    assert run(capsys, "--root", tmp_path, scenario / "case.lp") == (
        Exit.CLAIMS_HOLD,
        "1/1 passed\n",
    )


def test_without_root_a_subtree_is_its_own_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario = sibling_layout(tmp_path)
    code, out, err = run_both(capsys, tmp_path / "scenarios")
    assert code == Exit.FAULT
    assert f"which is outside the root {tmp_path / 'scenarios'}" in err
    assert "`--root`" in err
    assert out == "0/1 passed, 1 error\n"
    assert run_both(capsys, scenario / "case.lp")[0] == Exit.FAULT


def test_root_still_refuses_an_include_that_leaves_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sibling_layout(tmp_path)
    code, _out, err = run_both(capsys, "--root", tmp_path / "scenarios", tmp_path / "scenarios")
    assert code == Exit.FAULT
    assert f"which is outside the root {tmp_path / 'scenarios'}" in err


def test_a_path_outside_the_root_is_refused_and_the_rest_still_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    write(root, "in.lp", "p.\n% @expect sat\n")
    stray = write(tmp_path, "stray.lp", "secret(42).\n% @expect sat\n")
    code, out, err = run_both(capsys, "--root", root, root, stray)
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: `{stray}` is outside the root {root}"
    assert "help: name paths under the root, or choose a root that holds them" in err
    assert "secret(42)" not in err
    assert out == "1/2 passed, 1 error\n"


@pytest.mark.parametrize(
    ("argument", "held"),
    [
        ("root/../stray.lp", False),
        ("root/sub/../in.lp", True),
        ("root/..", False),
        ("root", True),
    ],
)
def test_root_compares_paths_after_resolving_dot_dot(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argument: str, *, held: bool
) -> None:
    root = tmp_path / "root"
    (root / "sub").mkdir(parents=True)
    write(root, "in.lp", "p.\n% @expect sat\n")
    write(tmp_path, "stray.lp", "p.\n% @expect sat\n")
    code, _out, err = run_both(capsys, "--root", root, tmp_path / argument)
    assert (code == Exit.CLAIMS_HOLD) is held
    assert ("is outside the root" in err) is not held


def test_root_follows_symbolic_links_before_it_compares(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    write(elsewhere, "case.lp", "p.\n% @expect sat\n")
    (root / "file.lp").symlink_to(elsewhere / "case.lp")
    (root / "dir").symlink_to(elsewhere, target_is_directory=True)
    for linked in (root / "file.lp", root / "dir"):
        code, _out, err = run_both(capsys, "--root", root, linked)
        assert code == Exit.FAULT
        assert f"`{linked}` is outside the root {root}" in err
    alias = tmp_path / "alias"
    alias.symlink_to(elsewhere, target_is_directory=True)
    assert run(capsys, "--root", alias, elsewhere) == (Exit.CLAIMS_HOLD, "1/1 passed\n")


def test_a_walked_link_out_of_the_root_is_refused_by_containment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = write(tmp_path, "case.lp", "p.\n% @expect sat\n")
    (root / "link.lp").symlink_to(outside)
    code, _out, err = run_both(capsys, "--root", root, root)
    assert code == Exit.FAULT
    assert f"this case loads {outside}, which is outside the root {root}" in err


@pytest.mark.parametrize("name", ["absent", "file.lp"])
def test_root_must_be_a_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    write(tmp_path, "file.lp", "p.\n% @expect sat\n")
    with pytest.raises(SystemExit) as usage:
        main(["--root", str(tmp_path / name), str(tmp_path)])
    assert usage.value.code == Exit.FAULT
    assert f"`{tmp_path / name}` is not a directory" in capsys.readouterr().err


def test_a_refused_path_is_a_fault_entry_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    stray = write(tmp_path, "stray.lp", "p.\n% @expect sat\n")
    code, out = run(capsys, "--json", "--root", root, stray)
    assert code == Exit.FAULT
    (entry,) = json.loads(out)["run"]["entries"]
    assert entry["source"] == str(stray)
    assert entry["result"]["kind"] == "fault"


def test_refusals_keep_the_order_the_paths_were_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    first = write(root, "a.lp", "p.\n% @expect sat\n")
    stray = write(tmp_path, "stray.lp", "p.\n% @expect sat\n")
    last = write(root, "b.lp", "p.\n% @expect sat\n")
    code, out = run(capsys, "--json", "--root", root, first, stray, last)
    assert code == Exit.FAULT
    entries = json.loads(out)["run"]["entries"]
    assert [entry["source"] for entry in entries] == [str(first), str(stray), str(last)]


def test_a_symbolic_link_loop_is_unreadable_not_a_crash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "x.lp").symlink_to(root / "y.lp")
    (root / "y.lp").symlink_to(root / "x.lp")
    write(root, "ok.lp", "p.\n% @expect sat\n")
    for argv in (["--root", root, root / "x.lp"], [root / "x.lp"], ["--root", root, root]):
        code, out, err = run_both(capsys, "--color", "never", *argv)
        assert code == Exit.FAULT
        assert "cannot read" in err
        assert "error" in out


def base_and_scenarios(tmp_path: Path, base: str = "#const n = 2.\nnum(1..n).\n") -> Path:
    """Lay out a base under `encodings/` and a case in each of two sibling scenario subtrees."""
    (tmp_path / "encodings").mkdir(parents=True)
    library = write(tmp_path / "encodings", "base.lp", base)
    for name, claim in (("a", "@cautious { num(2) }"), ("b", "@count 1")):
        (tmp_path / "scenarios" / name).mkdir(parents=True)
        write(tmp_path / "scenarios" / name, "case.lp", f"% @expect sat\n% {claim}\n")
    return library


def test_with_loads_a_library_with_every_walked_case_under_the_common_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = base_and_scenarios(tmp_path)
    scenarios = tmp_path / "scenarios"
    assert run(capsys, scenarios, "--with", library) == (Exit.CLAIMS_HOLD, "2/2 passed\n")
    named = (scenarios / "a" / "case.lp", scenarios / "b" / "case.lp")
    assert run(capsys, *named, "--with", library) == (Exit.CLAIMS_HOLD, "2/2 passed\n")
    code, _out, err = run_both(capsys, scenarios)
    assert code == Exit.CLAIM_UNMET
    assert err == ""


def test_with_and_explain_find_evidence_in_the_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = write(tmp_path, "base.lp", "num(1..2).\nbig :- num(2).\n")
    case = write(tmp_path, "case.lp", "% @expect sat\n% @query no { big }\n")
    code, out = run(capsys, "explain", case, "--with", library, "--format", "text", "--spans")
    assert code == Exit.CLAIM_UNMET
    assert "[FAIL] @query no { big }" in out
    assert f"= {library}:2: big :- num(2)." in out


@pytest.mark.parametrize(
    "asked", [("why", "case.lp", "top", "--answer-set", "1"), ("explain", "case.lp")]
)
def test_a_rule_from_another_file_is_labelled_with_its_file_and_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    asked: tuple[str, ...],
) -> None:
    write(tmp_path, "case.lp", "top :- derived(1).\n% @expect sat\n% @query no { top }\n")
    write(tmp_path, "enc.lp", "base(1).\nderived(X) :- base(X).\n")
    monkeypatch.chdir(tmp_path)
    _code, out = run(capsys, *asked, "--with", "enc.lp", "--format", "text")
    steps = [
        line.strip() for line in out.splitlines() if line.strip().startswith(("top", "└", "base"))
    ]
    assert [step.split()[-1] for step in steps] == ["1", "enc.lp:2", "enc.lp:1"]
    assert steps[0].endswith("  line 1")
    assert steps[2].endswith("  fact, enc.lp:1")


def test_with_keeps_the_order_given_and_json_lists_what_each_case_loads(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = write(tmp_path, "first.lp", "p.\n")
    second = write(tmp_path, "second.lp", "q :- p.\n")
    loading = write(
        tmp_path, "loading.lp", '#include "second.lp".\n% @expect sat\n% @cautious { q }\n'
    )
    plain = write(tmp_path, "plain.lp", "% @expect sat\n% @cautious { q }\n")
    argv = ["--json", loading, plain, "--with", first, "--with", second]
    code, out = run(capsys, *argv)
    assert code == Exit.CLAIMS_HOLD
    entries = json.loads(out)["run"]["entries"]
    assert [entry.get("libraries") for entry in entries] == [
        [str(first)],
        [str(first), str(second)],
    ]
    _code, out = run(capsys, "--json", plain)
    assert "libraries" not in json.loads(out)["run"]["entries"][0]


@pytest.mark.parametrize("linked", [False, True])
def test_a_library_the_case_already_includes_is_loaded_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, linked: bool
) -> None:
    """A second load of the base would define `n` twice, an error on any platform."""
    library = base_and_scenarios(tmp_path)
    case = write(
        tmp_path / "scenarios" / "a",
        "case.lp",
        '#include "../../encodings/base.lp".\n% @expect sat\n% @cautious { num(2) }\n',
    )
    named = library
    if linked:
        named = tmp_path / "encodings" / "link.lp"
        named.symlink_to(library)
    code, out, err = run_both(capsys, "--json", case, "--with", named)
    assert (code, err) == (Exit.CLAIMS_HOLD, "")
    assert "libraries" not in json.loads(out)["run"]["entries"][0]


def test_with_a_root_given_a_library_outside_it_is_refused_and_no_case_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = base_and_scenarios(tmp_path)
    scenarios = tmp_path / "scenarios"
    code, out, err = run_both(capsys, "--root", scenarios, scenarios, "--with", library)
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: `{library}` is outside the root {scenarios}"
    assert out == "0/1 passed, 1 error\n"


def test_an_include_of_a_library_is_held_to_the_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    outside = write(tmp_path, "secret.lp", "secret(42).\n")
    project = tmp_path / "project"
    project.mkdir()
    library = write(project, "base.lp", f'#include "{outside}".\n')
    case = write(project, "case.lp", "% @expect sat\n")
    code, out, err = run_both(capsys, case, "--with", library)
    assert code == Exit.FAULT
    assert f"this case loads {outside}, which is outside the root {project}" in err
    assert "secret(42)" not in err + out


def test_a_library_that_carries_a_contract_tag_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = write(tmp_path, "case.lp", "% @expect sat\n")
    tagged = write(tmp_path, "other.lp", "p.\n% @expect sat\n")
    code, out, err = run_both(capsys, case, "--with", tagged)
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: `{tagged}` carries a contract tag"
    assert "= note: a `--with` file is a library: its claims would not be checked" in err
    assert "= help: name a case as a path, and a library with `--with`" in err
    assert out == "0/1 passed, 1 error\n"


def test_a_file_named_both_as_a_path_and_with_with_is_refused_and_the_rest_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = write(tmp_path, "base.lp", "p.\n")
    case = write(tmp_path, "case.lp", "% @expect sat\n% @cautious { p }\n")
    code, out, err = run_both(capsys, case, library, "--with", library)
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: `{library}` is named both as a path and with `--with`"
    assert "carries no contract tag" not in err
    assert out == "1/2 passed, 1 error\n"


def test_a_library_that_cannot_be_read_is_refused_as_any_path_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = write(tmp_path, "case.lp", "% @expect sat\n")
    (tmp_path / "latin1.lp").write_bytes(b"p(\xe9).\n")
    for library, note in (
        (tmp_path / "absent.lp", "No such file or directory"),
        (tmp_path / "latin1.lp", "not valid UTF-8 at byte 2: invalid continuation byte"),
    ):
        code, _out, err = run_both(capsys, case, "--with", library)
        assert code == Exit.FAULT
        assert err.splitlines()[0] == f"error: cannot read `{library}`"
        assert note in err


def test_a_syntax_error_in_a_library_points_into_the_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = write(tmp_path, "base.lp", "p.\nq :- p(.\n")
    case = write(tmp_path, "case.lp", "% @expect sat\n")
    code, _out, err = run_both(capsys, "--short", case, "--with", library)
    assert code == Exit.FAULT
    assert err.startswith(f"{library}:2:")


def test_a_default_root_inside_the_home_directory_is_kept(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    library = base_and_scenarios(tmp_path / "home" / "me")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    scenarios = tmp_path / "home" / "me" / "scenarios"
    assert run(capsys, scenarios, "--with", library) == (Exit.CLAIMS_HOLD, "2/2 passed\n")


@pytest.mark.parametrize(
    ("home", "why"),
    [
        ("home/me", "it is the home directory"),
        ("home/me/deep", "it holds the home directory"),
    ],
)
def test_a_default_root_that_holds_the_home_directory_is_refused(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    home: str,
    why: str,
) -> None:
    me = tmp_path / "home" / "me"
    (me / "project").mkdir(parents=True)
    case = write(me / "project", "case.lp", "% @expect sat\n")
    library = write(me, "base.lp", "p.\n")
    monkeypatch.setenv("HOME", str(tmp_path / home))
    code, out, err = run_both(capsys, case, "--with", library)
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: the default root {me} is too wide"
    assert f"= note: {why}" in err
    assert "= help: name the project's directory as the root (`--root` on the command line" in err
    assert out == "0/1 passed, 1 error\n"
    assert run(capsys, case, "--with", library, "--root", me)[0] == Exit.CLAIMS_HOLD
    monkeypatch.delenv("HOME")
    assert run(capsys, case, "--with", library)[0] == Exit.CLAIMS_HOLD


@pytest.mark.parametrize(
    "asked", [("why", "p", WhyExit.FAULT), ("ask", "{ p }", AskExit.FAULT)], ids=["why", "ask"]
)
def test_why_and_ask_refuse_a_default_root_that_holds_the_home_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    asked: tuple[str, str, int],
) -> None:
    command, question, fault = asked
    me = tmp_path / "me"
    (me / "project").mkdir(parents=True)
    case = write(me / "project", "case.lp", "q.\n")
    library = write(me, "base.lp", "p.\n")
    monkeypatch.setenv("HOME", str(me))
    code, _out, err = run_both(
        capsys, command, case, question, "--with", library, "--format", "text"
    )
    assert code == fault
    assert err.splitlines()[0] == f"error: the default root {me} is too wide"


@pytest.mark.parametrize("command", ["why", "ask"])
def test_why_and_ask_refuse_a_directory_as_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    with pytest.raises(SystemExit) as usage:
        main([command, str(tmp_path), "p"])
    assert usage.value.code == Exit.FAULT
    assert f"`{tmp_path}` is a directory, not a `.lp` file" in capsys.readouterr().err


@pytest.mark.parametrize(
    "asked",
    [("test",), ("explain",), ("why", "p"), ("ask", "{ p }")],
    ids=["test", "explain", "why", "ask"],
)
def test_a_linked_case_is_held_to_the_directory_it_resolves_to(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], link: Link, asked: tuple[str, ...]
) -> None:
    real, alias = tmp_path / "real", tmp_path / "alias"
    for directory in (real, alias):
        directory.mkdir()
    write(real, "case.lp", "q :- p.\n% @expect sat\n% @cautious { q }\n")
    library = write(alias, "base.lp", "p.\n")
    link(alias / "case.lp", real / "case.lp")
    command, *question = asked
    argv = [command, alias / "case.lp", *question, "--with", library, "--format", "text"]
    code, _out, err = run_both(capsys, *argv)
    assert (code, err) == (0, "")


def test_a_default_root_that_is_the_file_system_root_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = write(tmp_path, "case.lp", "% @expect sat\n")
    library = Path(Path.cwd().anchor, "dev", "null")
    code, _out, err = run_both(capsys, case, "--with", library)
    assert code == Exit.FAULT
    assert err.splitlines()[0] == f"error: the default root {library.anchor} is too wide"
    assert "= note: it is the root of the file system" in err


def test_why_and_ask_take_the_library_and_the_root_as_test_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    library = base_and_scenarios(tmp_path)
    case = tmp_path / "scenarios" / "a" / "case.lp"
    code, out = run(
        capsys, "why", case, "num(2)", "--answer-set", "1", "--with", library, "--format", "text"
    )
    assert (code, out.splitlines()[0]) == (WhyExit.EXPLAINED, "why: num(2)")
    code, out = run(capsys, "ask", case, "num(2)", "--with", library, "--format", "json")
    assert (code, json.loads(out)["ask"]["kind"]) == (AskExit.ANSWERED, "answered")
    including = write(case.parent, "including.lp", '#include "../../encodings/base.lp".\n')
    for command in (
        ["why", including, "num(2)", "--answer-set", "1"],
        ["ask", including, "num(2)"],
    ):
        code, out = run(capsys, *command, "--format", "json")
        assert code == WhyExit.FAULT
        assert "which is outside the root" in out
        assert run(capsys, *command, "--root", tmp_path, "--format", "json")[0] == 0


@pytest.mark.parametrize("command", [["why", "{path}", "p"], ["ask", "{path}", "p"]])
def test_why_and_ask_refuse_each_library_under_its_own_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: list[str]
) -> None:
    case = write(tmp_path, "case.lp", "p.\n")
    tagged = write(tmp_path, "tagged.lp", "p.\n% @expect sat\n")
    absent = tmp_path / "absent.lp"
    argv = [part.format(path=case) for part in command]
    code, _out, err = run_both(
        capsys, *argv, "--with", tagged, "--with", absent, "--format", "text"
    )
    assert code == WhyExit.FAULT
    assert f"error: `{tagged}` carries a contract tag\n --> {tagged}\n" in err
    assert f"error: cannot read `{absent}`\n --> {absent}\n" in err
    code, out = run(capsys, *argv, "--with", tagged, "--with", absent, "--json")
    messages = [d["message"] for d in json.loads(out)[command[0]]["diagnostics"]]
    assert messages == [f"`{tagged}` carries a contract tag", f"cannot read `{absent}`"]


def test_why_refuses_a_program_outside_its_root_or_named_with_with(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    case = write(tmp_path, "case.lp", "p.\n")
    code, _out, err = run_both(
        capsys, "why", case, "p", "--answer-set", "1", "--root", root, "--format", "text"
    )
    assert code == WhyExit.FAULT
    assert err.splitlines()[0] == f"error: `{case}` is outside the root {root}"
    code, _out, err = run_both(
        capsys, "why", case, "p", "--answer-set", "1", "--with", case, "--format", "text"
    )
    assert code == WhyExit.FAULT
    assert err.splitlines()[0] == f"error: `{case}` is named both as a path and with `--with`"


def test_a_walked_note_on_a_renamed_tag_gives_its_spelling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "ok.lp", "a.\n% @expect sat\n")
    write(tmp_path, "old.lp", "a.\n% @model { a }\n% @expct sat\n")
    code, _out, err = run_both(capsys, "--color", "never", tmp_path)
    assert code == Exit.CLAIMS_HOLD
    assert (
        f"`{tmp_path / 'old.lp'}` carries no contract tag; `@model`, `@expct` are not tags" in err
    )
    assert "help: the tag is spelled `@answer-set`" in err
    assert "help: there is a tag with a similar name: `@expect`" in err
    assert "did you mean" not in err


def test_a_walked_note_on_one_unknown_tag_says_it_is_not_a_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "ok.lp", "a.\n% @expect sat\n")
    write(tmp_path, "old.lp", "a.\n% @model { a }\n% @model { b }\n")
    _code, _out, err = run_both(capsys, "--color", "never", tmp_path)
    assert f"`{tmp_path / 'old.lp'}` carries no contract tag; `@model` is not a tag\n" in err
    assert err.count("the tag is spelled `@answer-set`") == 1


@pytest.mark.parametrize(
    ("text", "shown", "tip"),
    [
        ("a.\n% @model { a }\n", "`@model` is not a tag", "the tag is spelled `@answer-set`"),
        (
            "a.\n% @expct sat\n",
            "`@expct` is not a tag",
            "there is a tag with a similar name: `@expect`",
        ),
    ],
)
def test_a_named_file_with_only_a_mistaken_tag_is_told_the_tag(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], text: str, shown: str, tip: str
) -> None:
    path = write(tmp_path, "old.lp", text)
    code, _out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert f"error: `{path}` carries no contract tag\n" in err
    assert f"= note: {shown}\n" in err
    assert f"= help: {tip}\n" in err
    assert "a contract-free `.lp` is a library" not in err


ABSENT = (
    "flagged(ann). role(ann,admin).\n"
    "access(U) :- role(U,admin), not suspended(U).\n"
    "suspended(U) :- flagged(U).\n"
    "% @expect sat\n% @cautious { access(ann) }\n"
)


def test_explain_shows_the_evidence_and_exits_as_test_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "a.lp", ABSENT)
    code, out = run(capsys, "explain", path)
    assert code == Exit.CLAIM_UNMET
    assert "evidence: @cautious { access(ann) }" in out
    assert "blocked by not suspended(ann)" in out
    tested, plain = run(capsys, "test", path)
    assert tested == code
    assert "evidence" not in plain


def test_explain_with_spans_shows_each_rule_as_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "a.lp", ABSENT)
    _, out = run(capsys, "explain", "--spans", path)
    assert f"= {path}:2: access(U) :- role(U,admin), not suspended(U). {{U=ann}}" in out


def test_explain_as_json_adds_the_evidence_to_the_run_test_writes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "a.lp", ABSENT)
    _, explained = run(capsys, "explain", "--json", path)
    _, tested = run(capsys, "test", "--json", path)
    with_evidence, without = json.loads(explained), json.loads(tested)
    (finding,) = [
        f for f in with_evidence["run"]["entries"][0]["result"]["findings"] if "evidence" in f
    ]
    assert finding["evidence"]["max_depth"] == 3
    del finding["evidence"]
    assert with_evidence == without


def test_explain_takes_a_depth_or_all_and_refuses_anything_else(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "a.lp", ABSENT)
    _, out = run(capsys, "explain", "--max-depth", "all", "--json", path)
    assert '"max_depth": "all"' in out
    for refused in ("0", "-1", "x"):
        with pytest.raises(SystemExit) as stopped:
            main(["explain", "--max-depth", refused, str(path)])
        assert stopped.value.code == Exit.FAULT
    capsys.readouterr()


def test_explain_of_a_passing_case_is_its_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "d.lp", DRINKS + "% @expect sat\n% @count 2\n")
    assert run(capsys, "explain", path) == run(capsys, "test", path)


def test_the_explain_options_are_described_as_the_reference_describes_them(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        main(["explain", "--help"])
    words = " ".join(capsys.readouterr().out.split())
    assert (
        "how many absent atoms deep an explanation goes, or `all` for no limit (default: 3)"
        in words
    )
    assert (
        "show each rule as written, its place and its substitution, beneath its instance" in words
    )


# `why` and `ask`: one program, one question, written in the layout of `explain`.

CHAIN = "edge(a,b). edge(b,c).\nreach(a).\nreach(Y) :- reach(X), edge(X,Y).\n"
CHOICE = "{ a; b }.\n-c.\n"


def test_why_explains_an_atom_in_the_first_answer_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "chain.lp", CHAIN)
    code, out, err = run_both(capsys, "why", path, "reach(c)", "--answer-set", "1")
    assert (code, err) == (WhyExit.EXPLAINED, "")
    assert out == (
        "why: reach(c)\n"
        f" --> {path}\n"
        "  |\n"
        "  = answer set 1: { edge(a,b), edge(b,c), reach(a), reach(b), reach(c) }\n"
        "  |\n"
        "  reach(c) :- reach(b), edge(b,c).  line 3\n"
        "  ├── reach(b) :- reach(a), edge(a,b).  line 3\n"
        "  │   ├── reach(a)                  fact, line 2\n"
        "  │   └── edge(a,b)                 fact, line 1\n"
        "  └── edge(b,c)                     fact, line 1\n"
        "  |\n"
        "  = note: support is sound, not minimal\n"
        "\n"
    )


def test_why_names_the_answer_set_asked_for_and_the_optima_as_optimal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    _, out = run(capsys, "why", path, "not a", "--answer-set", "2")
    assert "  = answer set 2: { b, -c }\n" in out
    assert out.startswith("why: not a\n")
    _, out = run(capsys, "why", path, "a", "--answer-set", "2", "--over", "optimal")
    assert "  = optimal answer set 2 of 4: " in out
    assert "counterexample" not in out


def test_why_under_assumptions_explains_their_answer_sets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "why", path, "a", "--answer-set", "1", "--assuming", "{ b, not a }")
    assert code == WhyExit.EXPLAINED
    assert "  = answer set 1: { b, -c }\n" in out


def test_why_without_an_answer_set_shows_the_refutation_and_exits_as_a_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "why", path, "a", "--answer-set", "1", "--assuming", "a, not a")
    assert code == WhyExit.FAULT
    assert out == (
        f"why: a\n --> {path}\n  |\n"
        "  = refutation: no answer set satisfies the assumptions (not a, a)\n\n"
    )


def test_why_past_the_last_answer_set_is_a_fault_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out, err = run_both(capsys, "why", path, "a", "--answer-set", "9")
    assert (code, out) == (WhyExit.FAULT, "")
    assert err == (
        "error: there is no answer set 9: the search read 4\n"
        f" --> {path}\n"
        "  |\n"
        "  = help: `--answer-set` counts from 1 to 4\n"
    )
    _, _, short = run_both(capsys, "why", path, "a", "--answer-set", "9", "--short")
    assert short == f"{path}: error: there is no answer set 9: the search read 4\n"


def test_why_on_a_search_cut_short_says_so_and_exits_unmet(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "why", path, "a", "--answer-set", "3", "--max-answer-sets", "1")
    assert code == WhyExit.ENDED
    assert "  = search ended: answer-set limit reached (--max-answer-sets)\n" in out


def test_why_refuses_an_atom_that_is_not_ground_where_it_was_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "chain.lp", CHAIN)
    code, out, err = run_both(capsys, "why", path, "p(X)", "--answer-set", "1")
    assert (code, out) == (WhyExit.FAULT, "")
    assert err == (
        "error: atom asked about is not ground\n"
        " --> QUERY:1:1\n"
        "  |\n"
        "1 | p(X)\n"
        "  | ^^^^ has a variable\n"
    )
    code, _, err = run_both(capsys, "why", path, "a", "--answer-set", "1", "--assuming", "p(X)")
    assert code == WhyExit.FAULT
    assert err.startswith("error: assumption is not ground\n --> --assuming:1:1\n")


def test_why_of_a_missing_file_is_a_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, err = run_both(capsys, "why", tmp_path / "absent.lp", "a")
    assert code == WhyExit.FAULT
    assert err.startswith("error: cannot read")


def test_ask_answers_with_the_first_answer_set_giving_each_value(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out, err = run_both(capsys, "ask", path, "a")
    assert (code, err) == (AskExit.ANSWERED, "")
    assert out == (
        "ask: { a }\n"
        f" --> {path}\n"
        "  |\n"
        "  = answer: unknown\n"
        "  = neither a nor -a in answer set 1: { -c }\n"
        "  = true in answer set 3: { a, -c }\n"
        "  |\n"
        f"  = help: `elenctic why {path} a --answer-set 1` shows why\n"
        "\n"
    )


def test_ask_answers_past_a_limit_and_says_which_answer_sets_it_did_not_reach(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out, err = run_both(capsys, "ask", path, "a", "--max-answer-sets", "2")
    assert (code, err) == (AskExit.ANSWERED, "")
    assert out == (
        "ask: { a }\n"
        f" --> {path}\n"
        "  |\n"
        "  = answer: unknown\n"
        "  = neither a nor -a in answer set 1: { -c }\n"
        "  = true in an answer set past the 2 read: search ended: answer-set limit reached"
        " (--max-answer-sets)\n"
        "  |\n"
        f"  = help: `elenctic why {path} a --answer-set 1` shows why\n"
        "\n"
    )
    code, out = run(capsys, "ask", path, "a", "--max-answer-sets", "2", "--json")
    asked = json.loads(out)["ask"]
    assert asked["unreached"] == [
        {"kind": "unreached", "answer": "yes", "read": 2, "cut": "max_answer_sets"}
    ]


def test_ask_answers_no_and_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "ask", path, "{ c }")
    assert code == AskExit.ANSWERED
    assert "  = answer: no\n  = false in answer set 1: { -c }\n" in out


def test_ask_of_a_conjunction_says_neither_true_nor_false_and_offers_no_why(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    _, out = run(capsys, "ask", path, "{ a, b }")
    assert "  = neither true nor false in answer set 1 of 4: { -c }\n" in out
    assert "help" not in out


def test_ask_over_the_optima_names_them_and_its_help_keeps_the_range(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    _, out = run(capsys, "ask", path, "a", "--over", "optimal")
    assert "in optimal answer set 1 of 4" in out
    assert "--answer-set 1 --over optimal` shows why" in out


def test_ask_of_a_pattern_writes_its_bindings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "p.lp", "p(1). { p(2) }. -p(3).\n")
    _, out = run(capsys, "ask", path, "{ p(X) }")
    assert out == (
        f"ask: {{ p(X) }}\n --> {path}\n  |\n"
        "  = bindings: 1 yes, 1 no, 1 unknown (`--unknown` shows them)\n"
        "  = yes: X = 1\n  = no: X = 3\n  = no more bindings\n\n"
    )
    _, out = run(capsys, "ask", path, "{ p(X) }", "--unknown")
    assert out.endswith(
        "  = bindings: 1 yes, 1 no, 1 unknown\n"
        "  = yes: X = 1\n  = no: X = 3\n  = unknown: X = 2\n  = no more bindings\n\n"
    )
    _, out = run(capsys, "ask", write(tmp_path, "q.lp", "q(1, a).\n"), "q(X, Y)")
    assert out.endswith(
        "  = bindings: 1 yes, 0 no, 0 unknown\n  = yes: X = 1, Y = a\n  = no more bindings\n\n"
    )


def test_ask_of_a_cautious_query_counts_the_bindings_not_entailed_and_shows_its_yes_ones(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "r.lp", "r(a). r(b). { c(b); c(c) } = 1.\n")
    _, out = run(capsys, "ask", path, "r(X), not c(X)", "--mode", "cautious")
    assert out.endswith(
        "  = bindings: 1 yes, 1 not entailed\n  = yes: X = a\n  = no more bindings\n\n"
    )


def test_ask_of_a_brave_query_cut_short_shows_the_yes_bindings_found_and_what_cut_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "p.lp", "p(1). { p(2) }.\n")
    code, out = run(capsys, "ask", path, "p(X)", "--mode", "brave", "--max-answer-sets", "1")
    assert code == AskExit.ENDED
    assert "  = bindings: 1 yes so far\n  = yes: X = 1\n" in out
    assert out.endswith("  = search ended: answer-set limit reached (--max-answer-sets)\n\n")


def test_ask_refuses_unknown_bindings_for_a_query_without_variables(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, err = run_both(capsys, "ask", write(tmp_path, "a.lp", "a.\n"), "a", "--unknown")
    assert (code, out) == (AskExit.FAULT, "")
    assert err.startswith("error: a query without variables has no unknown bindings to show\n")


def test_ask_refuses_a_query_the_query_tag_refuses(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out, err = run_both(capsys, "ask", path, "{ a ; b }")
    assert (code, out) == (AskExit.FAULT, "")
    assert err.startswith("error: query uses a semicolon\n --> QUERY:1:5\n")
    code, _, err = run_both(capsys, "ask", tmp_path / "absent.lp", "a")
    assert code == AskExit.FAULT


def test_ask_of_not_answers_as_the_literal_is_absent_or_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    _, out = run(capsys, "ask", path, "not c")
    assert "  = answer: yes\n" in out
    _, out = run(capsys, "ask", path, "{ not a, not -c }.")
    assert out.startswith("ask: { not a, not -c }\n")
    assert "  = answer: no\n" in out


@pytest.mark.parametrize("command", ["ask", "why"])
def test_a_query_or_atom_that_starts_with_a_classical_negation_is_not_an_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, command, path, "-c", "--over", "optimal")
    assert code == 0
    assert "-c" in out.splitlines()[0]


def test_a_query_with_a_classical_negation_and_variables_is_not_an_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "p.lp", "-p(3).\n")
    code, out = run(capsys, "ask", path, "-p(X)")
    assert code == AskExit.ANSWERED
    assert out.startswith("ask: { -p(X) }\n")


def test_ask_without_answer_sets_shows_the_refutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "none.lp", "a. :- a.\n")
    code, out = run(capsys, "ask", path, "a")
    assert code == AskExit.FAULT
    assert "  = refutation: the program has no answer set, and nothing is assumed\n" in out


def test_why_and_ask_write_json_under_their_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "why", path, "a", "--answer-set", "1", "--json")
    document = json.loads(out)
    assert (code, document["schema"], document["exit_code"]) == (0, 1, 0)
    assert document["why"]["kind"] == "explanation"
    code, out = run(capsys, "ask", path, "a", "--format", "json")
    answered = json.loads(out)["ask"]
    assert answered["kind"] == "answered"
    assert answered["answer"] == "unknown"
    assert [t["index"] for t in answered["taken"]] == [1, 3]
    code, out = run(capsys, "ask", path, "{ a ; b }", "--json")
    assert (code, json.loads(out)["ask"]["kind"]) == (AskExit.FAULT, "fault")
    code, out = run(capsys, "why", path, "a", "--answer-set", "9", "--json")
    assert json.loads(out) == {
        "schema": 1,
        "why": json.loads(out)["why"],
        "exit_code": WhyExit.FAULT,
    }


def test_an_internal_error_in_why_or_ask_is_one_line_and_exits_3(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)

    def broken(*_: object, **__: object) -> object:
        message = "boom"
        raise RuntimeError(message)

    monkeypatch.setattr("elenctic.cli.why", broken)
    monkeypatch.setattr("elenctic.cli.ask", broken)
    code, out, err = run_both(capsys, "why", path, "a", "--answer-set", "1")
    assert (code, out, err) == (
        WhyExit.INTERNAL_ERROR,
        "",
        "elenctic: internal error: RuntimeError: boom\n",
    )
    code, out = run(capsys, "ask", path, "a", "--json")
    assert code == AskExit.INTERNAL_ERROR
    assert json.loads(out)["ask"]["kind"] == "internal"


@pytest.mark.parametrize("index", ["0", "-1", "two", "1.5"])
def test_an_answer_set_index_is_a_positive_integer_or_a_usage_error(
    index: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    with pytest.raises(SystemExit) as stopped:
        main(["why", str(path), "a", "--answer-set", "1", f"--answer-set={index}"])
    assert stopped.value.code == WhyExit.FAULT
    assert f"{index!r} is not a positive integer" in capsys.readouterr().err


def test_the_answer_set_index_accepts_an_equals_sign(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    assert run(capsys, "why", path, "a", "--answer-set=1") == run(
        capsys, "why", path, "a", "--answer-set", "1"
    )


def test_the_why_a_help_line_gives_can_be_pasted_into_a_shell(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "it's.lp", 'q("it\'s").\n')
    _, out = run(capsys, "ask", path, 'q("it\'s")')
    (line,) = [each for each in out.splitlines() if "= help:" in each]
    command = line.split("`")[1]
    assert shlex.split(command) == ["elenctic", "why", str(path), 'q("it\'s")', "--answer-set", "1"]


@pytest.mark.parametrize(
    ("asked", "heading"),
    [
        ("a", "why: a\n"),
        ("not a", "why: not a\n"),
        ("  not   a ", "why: not a\n"),
        ("-c", "why: -c\n"),
        ("not -c", "why: not -c\n"),
    ],
)
def test_why_is_headed_by_the_atom_as_it_was_asked_written_as_a_step_writes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], asked: str, heading: str
) -> None:
    """`not a` asks what `a` does; the heading keeps the `not`, in the legend's spelling."""
    path = write(tmp_path, "ab.lp", CHOICE)
    _, out = run(capsys, "why", path, "--answer-set", "1", "--", asked)
    assert out.startswith(heading)


def test_why_as_json_names_the_literal_by_its_roots_with_or_without_not(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """JSON has no heading: its roots say whether the atom holds, as they did before."""
    path = write(tmp_path, "ab.lp", CHOICE)
    held, unheld = (
        run(capsys, "why", path, asked, "--answer-set", "1", "--format", "json")[1]
        for asked in ("a", "not a")
    )
    assert held == unheld


@pytest.mark.parametrize(
    "invocation",
    [
        ("project", ["test", "."], None),
        ("project", ["test", "--root", "tests", "tests"], "project/base.lp"),
        (".", ["test", "project/tests"], "base.lp"),
    ],
)
def test_root_holds_an_include_that_clingo_finds_from_the_working_directory(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    invocation: tuple[str, list[str], str | None],
) -> None:
    working, argv, escaped = invocation
    tests = tmp_path / "project" / "tests"
    tests.mkdir(parents=True)
    write(tmp_path / "project", "base.lp", "q.\n")
    write(tmp_path, "base.lp", "q.\n")
    write(tests, "unit-test.lp", '#include "base.lp".\n% @expect sat\n% @cautious { q }\n')
    monkeypatch.chdir(tmp_path / working)
    code, out, err = run_both(capsys, *argv)
    if escaped is None:
        assert (code, out) == (Exit.CLAIMS_HOLD, "1/1 passed\n")
    else:
        assert code == Exit.FAULT
        assert f"this case loads {tmp_path / escaped}, which is outside the root" in err


@pytest.mark.parametrize(
    ("mode", "literal", "expected"),
    [
        ("default", "c", "no"),
        ("cautious", "c", "not entailed"),
        ("cautious", "a", "not entailed"),
        ("brave", "a", "yes"),
        ("brave", "c", "none holds"),
        ("brave", "not zz", "yes"),
    ],
)
def test_ask_takes_the_mode_its_help_names(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str, literal: str, expected: str
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "ask", path, literal, "--mode", mode)
    assert code == AskExit.ANSWERED
    assert f"  = answer: {expected}\n" in out
    code, out = run(capsys, "ask", path, literal, "--mode", mode, "--json")
    result = json.loads(out)["ask"]
    assert code == 0
    assert result["answer"] == expected.replace(" ", "_")
    assert result["mode"] == mode


def test_ask_help_names_the_default_semantics(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_:
        main(["ask", "--help"])
    assert exit_.value.code == 0
    help_ = capsys.readouterr().out
    assert "Gelfond\N{EN DASH}Kahl three-valued" in help_
    assert "gk" not in help_


def test_ask_of_a_conjunction_with_variables_writes_its_bindings_in_each_mode(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "r.lp", "r(a). r(b). { c(b); c(c) } = 1.\n")
    code, out = run(capsys, "ask", path, "--json", "r(X), not c(X)")
    found = json.loads(out)["ask"]["answer"]
    assert code == AskExit.ANSWERED
    assert found["kind"] == "answers"
    assert found["variables"] == ["X"]
    assert [(b["values"], b["answer"]) for b in found["bound"]] == [
        (["a"], "yes"),
        (["b"], "unknown"),
    ]
    code, out = run(capsys, "ask", path, "r(X), not c(X)", "--mode", "brave", "--json")
    found = json.loads(out)["ask"]["answer"]
    assert [(b["values"], b["answer"]) for b in found["bound"]] == [(["a"], "yes"), (["b"], "yes")]


def test_the_stream_of_the_library_is_the_order_ask_writes_its_bindings_in(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = "p(3). p(1). { p(2); p(4) }. -p(5). -p(0).\n"
    _, out = run(capsys, "ask", write(tmp_path, "p.lp", text), "p(X)", "--unknown")
    written = [line.removeprefix("  = ") for line in out.splitlines()[4:-2]]
    found = ask(Program(text, "p.lp"), Pattern("p", (Variable("X"),)))
    assert isinstance(found, Answered)
    assert written == [f"{b.answer}: X = {b.values[0]}" for b in stream(found, unknown=True)]
    assert written[0] == "yes: X = 1"


# `why PATH QUERY`: the warrant of the answer `ask` gives, in `ask`'s words.


def test_why_of_a_query_shows_what_warrants_its_answer_as_ask_names_the_answer_sets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out, err = run_both(capsys, "why", path, "-c")
    assert (code, err) == (WhyExit.EXPLAINED, "")
    assert out == (
        "why: { -c }\n"
        f" --> {path}\n"
        "  |\n"
        "  = answer: yes\n"
        "  = true in answer set 1: { -c }\n"
        "  = refutation: kept to the answer sets where it is not true, the program has no answer"
        " set, and nothing is assumed\n"
        "  |\n"
        f"  = help: `elenctic why {path} -c --answer-set 1` shows why\n"
        "\n"
    )
    _, asked = run(capsys, "ask", path, "-c")
    assert asked.splitlines()[3:5] == out.splitlines()[3:5]


def test_why_of_an_unknown_names_one_answer_set_where_it_is_not_true_and_one_not_false(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", "{ a; -a } = 1.\n")
    _, out = run(capsys, "why", path, "a")
    assert "  = answer: unknown\n  = false in answer set 1: { -a }\n" in out
    assert "  = true in answer set 2: { a }\n" in out
    assert "refutation" not in out


@pytest.mark.parametrize("query", ["a", "not a"])
def test_why_names_its_witnesses_in_the_order_ask_names_them(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], query: str
) -> None:
    path = write(tmp_path, "ab.lp", "{ a; -a } = 1.\n")
    _, asked = run(capsys, "ask", path, query)
    _, warranted = run(capsys, "why", path, query)
    assert warranted.splitlines()[3:6] == asked.splitlines()[3:6]


@pytest.mark.parametrize(
    ("mode", "lines"),
    [
        ("cautious", ["= answer: not entailed", "= neither a nor -a in answer set 1: { -c }"]),
        ("brave", ["= answer: yes", "= true in answer set 3: { a, -c }"]),
    ],
)
def test_why_takes_the_modes_ask_takes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], mode: str, lines: list[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    _, out = run(capsys, "why", path, "a", "--mode", mode)
    assert [line.strip() for line in out.splitlines()[3:5]] == lines
    assert "refutation" not in out


def test_why_of_a_brave_answer_none_holds_refutes_any_answer_set_where_it_is_true(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "why", path, "c", "--mode", "brave")
    assert code == WhyExit.EXPLAINED
    assert out.splitlines()[3:] == [
        "  = answer: none holds",
        (
            "  = refutation: kept to the answer sets where it is true, the program has no"
            " answer set, and nothing is assumed"
        ),
        "",
    ]


def test_why_of_a_binding_a_cut_brave_search_did_not_read_says_the_search_ended(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "p.lp", "{ p(1..3) }.")
    cut = ["--mode", "brave", "--max-answer-sets", "2"]
    code, out = run(capsys, "why", path, "p(X)", *cut, "--binding", "X = 3")
    assert code == WhyExit.ENDED
    assert out == (
        f"why: {{ p(3) }}\n --> {path}\n  |\n"
        "  = search ended: answer-set limit reached (--max-answer-sets)\n\n"
    )


def test_why_over_the_optima_is_shown_by_the_search_that_read_them_all(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    _, out = run(capsys, "why", path, "-c", "--over", "optimal")
    assert (
        "  = true in optimal answer set 1 of 4: { -c }\n  = read: all 4 optimal answer sets\n"
        in out
    )
    assert "--answer-set 1 --over optimal` shows why" in out


def test_why_of_a_query_with_variables_warrants_the_binding_written_as_ask_writes_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "r.lp", "r(a). r(b). { c(b) }. c(c).\n")
    _, listed = run(capsys, "ask", path, "{ r(X), not c(X) }")
    assert "  = yes: X = a\n" in listed
    code, out = run(capsys, "why", path, "{ r(X), not c(X) }", "--binding", "X = a")
    assert code == WhyExit.EXPLAINED
    assert out.startswith("why: { not c(a), r(a) }\n")
    assert "  = answer: yes\n  = true in answer set 1 of 2: { c(c), r(a), r(b) }\n" in out
    assert "help" not in out


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (["{ r(X) }", "--binding", "X = z"], "error: the query has no binding to X = z\n"),
        (["{ r(X) }", "--binding", "Y = a"], "error: `Y` is not a variable of the query\n"),
        (["r(a)", "--binding", "X = a"], "error: `X` is not a variable of the query\n"),
        (["r(a)", "--mode", "brave", "--answer-set", "1"], "error: `--mode` has no effect with"),
        (["r(a)", "--binding", "X = a", "--answer-set", "1"], "error: `--binding` has no effect"),
        (["r(a)", "--max-depth", "2"], "error: `--max-depth` has no effect without `--answer-set`"),
        (["r(a)", "--spans"], "error: `--spans` has no effect without `--answer-set`\n"),
        (["{ r(a) ; c(c) }"], "error: query uses a semicolon\n --> QUERY:1:8\n"),
    ],
)
def test_why_refuses_a_query_binding_or_option_as_ask_does_where_it_does_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: list[str], error: str
) -> None:
    path = write(tmp_path, "r.lp", "r(a). r(b). { c(b) }. c(c).\n")
    code, out, err = run_both(capsys, "why", path, *argv)
    assert (code, out) == (WhyExit.FAULT, "")
    assert err.startswith(error)


def test_why_of_a_query_with_variables_and_no_binding_says_how_to_name_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "r.lp", "r(a).\n")
    code, out, err = run_both(capsys, "why", path, "{ r(X), r(Y) }")
    assert (code, out) == (WhyExit.FAULT, "")
    assert err == (
        f"error: a query with variables is warranted one binding at a time\n --> {path}\n  |\n"
        "  = help: name one with `--binding 'X = \N{HORIZONTAL ELLIPSIS},"
        " Y = \N{HORIZONTAL ELLIPSIS}'`, as `ask` writes it\n"
    )


def test_why_of_a_query_without_answer_sets_or_cut_short_says_why_as_ask_does(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "why", path, "a", "--assuming", "a, not a")
    assert code == WhyExit.FAULT
    assert out == (
        f"why: {{ a }}\n --> {path}\n  |\n"
        "  = refutation: no answer set satisfies the assumptions (not a, a)\n\n"
    )
    code, out = run(capsys, "why", path, "{ a, b }", "--max-answer-sets", "1")
    assert code == WhyExit.ENDED
    assert "  = search ended: answer-set limit reached (--max-answer-sets)\n" in out


def test_why_of_a_query_writes_its_warrant_as_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "ab.lp", CHOICE)
    code, out = run(capsys, "why", path, "-c", "--json")
    warrant = json.loads(out)["why"]
    assert (code, warrant["kind"], warrant["answer"], warrant["mode"]) == (
        WhyExit.EXPLAINED,
        "warrant",
        "yes",
        "default",
    )
    assert [each["index"] for each in warrant["witnesses"]] == [1]
    assert warrant["refutation"]["kind"] == "no_assumptions"


def test_why_help_names_both_forms_and_the_modes_ask_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    helps = []
    for command in ("why", "ask"):
        with pytest.raises(SystemExit):
            main([command, "--help"])
        helps.append(" ".join(capsys.readouterr().out.split()))
    why_help, ask_help = helps
    mode = ask_help[ask_help.index("default: the") :].split("--unknown")[0].strip()
    assert mode in why_help
    assert "--binding X = V,..." in why_help
    assert "rather than warrant its answer" in why_help


@pytest.mark.skipif(not hasattr(signal, "SIGPIPE"), reason="no SIGPIPE on this platform")
def test_a_reader_that_stops_reading_ends_the_command_quietly(tmp_path: Path) -> None:
    """As `ls | head` does: the closed pipe ends the process, with nothing on stderr.

    No time limit: a search cut on a slow machine writes a few lines and exits 1 before the pipe
    closes.
    """
    write(tmp_path, "many.lp", "p(1..20000).\n")
    with subprocess.Popen(
        [sys.executable, "-m", "elenctic", "ask", "--max-seconds", "all", "many.lp", "p(X)"],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as process:
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdout.readline()
        process.stdout.close()
        error = process.stderr.read()
        status = process.wait()
    assert (status, error) == (-signal.SIGPIPE, b"")
