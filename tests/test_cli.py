import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from elenctic import check as real_check
from elenctic.cli import main
from elenctic.determination import Truncation, option
from elenctic.program import Program
from elenctic.report import Exit
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
    code, _out, err = run_both(capsys, "--color", "never", "--format", "short", tmp_path)
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
