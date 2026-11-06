"""X-1: elenctic never crashes on non-ASCII outside strings and comments."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from elenctic.check import check
from elenctic.cli import main
from elenctic.program import Fault, Locus, Program
from elenctic.report import Exit
from elenctic.spans import first_unlexable


def write(directory: Path, name: str, text: str) -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def run_both(capsys: pytest.CaptureFixture[str], *argv: object) -> tuple[int, str, str]:
    code = main([str(a) for a in argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_first_unlexable_points_at_the_character() -> None:
    found = first_unlexable("b :- a, é.\n", "t.lp")
    assert found is not None
    assert found.span is not None
    assert found.span.source == "t.lp"
    assert (found.span.start.line, found.span.start.column) == (1, 9)
    assert "é" in found.message


def test_first_unlexable_ignores_strings_and_comments() -> None:
    assert first_unlexable('p("é"). % é\n%* é *%\n', "t.lp") is None


def test_a_non_ascii_atom_is_a_program_fault_with_a_location(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "bad.lp", "a.\nb :- a, é.\n% @expect sat\n")
    code, out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert "error:" in err
    assert "é" in err
    assert "bad.lp:2:" in err
    assert out.endswith("error\n") or "error" in out


def test_a_non_ascii_tag_payload_is_a_contract_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "tag.lp", "a.\n% @expect sat\n% @cautious { é }\n")
    code, _out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert "error:" in err
    assert "é" in err


def test_non_ascii_in_string_or_comment_is_fine(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(
        tmp_path,
        "ok.lp",
        'a.\n% é in a comment is fine\nb("é").\n% @expect sat\n',
    )
    code, out = main([str(path)]), capsys.readouterr().out
    assert code == Exit.CLAIMS_HOLD
    assert "1/1 passed" in out


def test_json_still_emits_a_document_for_non_ascii(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, "bad.lp", "a.\nb :- a, é.\n% @expect sat\n")
    code, out, _err = run_both(capsys, "--json", path)
    assert code == Exit.FAULT
    document = json.loads(out)
    assert document["exit_code"] == Exit.FAULT
    assert document["schema"] == 1


def test_an_included_file_with_non_ascii_is_a_program_fault(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(tmp_path, "lib.lp", "b :- a, é.\n")
    path = write(tmp_path, "main.lp", '#include "lib.lp".\na.\n% @expect sat\n')
    code, _out, err = run_both(capsys, "--color", "never", path)
    assert code == Exit.FAULT
    assert "é" in err
    assert "lib.lp" in err


def test_check_returns_a_fault_rather_than_aborting() -> None:
    result = check(Program("a.\nb :- a, é.\n% @expect sat\n", "t.lp"))
    assert isinstance(result, Fault)
    assert result.locus is Locus.PROGRAM
    assert any("é" in d.message for d in result.diagnostics)


@given(st.text(alphabet=st.characters(min_codepoint=128), min_size=1, max_size=8))
@settings(max_examples=40, deadline=None)
def test_non_ascii_outside_strings_never_aborts_check(junk: str) -> None:
    text = f"a.\nb :- a, {junk}.\n% @expect sat\n"
    result = check(Program(text, "t.lp"))
    assert isinstance(result, Fault)
    assert result.locus is Locus.PROGRAM


def test_subprocess_does_not_die_silently_on_non_ascii(tmp_path: Path) -> None:
    path = write(tmp_path, "bad.lp", "a.\nb :- a, é.\n% @expect sat\n")
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "elenctic", "--json", str(path)],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert completed.returncode == Exit.FAULT
    document = json.loads(completed.stdout)
    assert document["exit_code"] == Exit.FAULT
