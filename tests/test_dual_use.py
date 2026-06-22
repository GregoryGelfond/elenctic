"""Dual-use: each inspectable pipeline-stage module runs under ``python -m`` (keystone #2).

The contract-parsing, discovery, run-derivation, and solve stages are each runnable standalone as a
debugging aid (``python -m elenctic.<stage> …``), in addition to being importable. The sub-component
and pure-data modules (``query``/``terms``/``result``/``checks``) are *not* given a ``__main__`` — a
standalone entry there would be artificial; their behaviour surfaces through the stage modules and
the ``elenctic`` console script (``cli``).
"""

import subprocess
import sys
from pathlib import Path


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def run_module(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    # -W error::RuntimeWarning turns the runpy "found in sys.modules" re-import warning into a
    # failure, so the lazy-__init__ fix (no eager submodule load) is pinned: any regression aborts.
    return subprocess.run(
        [sys.executable, "-W", "error::RuntimeWarning", "-m", f"elenctic.{module}", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_expectation_module_prints_the_parsed_contract(tmp_path: Path) -> None:
    contract = write(tmp_path / "c.lp", "% @expect sat\n% @model { a }\n")
    result = run_module("expectation", str(contract))
    assert result.returncode == 0
    assert "Sat" in result.stdout
    assert result.stderr == ""  # pristine: no runpy re-import warning (the lazy-__init__ contract)


def test_run_module_prints_the_derived_plan(tmp_path: Path) -> None:
    contract = write(tmp_path / "c.lp", "% @expect sat\n% @cautious { a }\n")
    result = run_module("run", str(contract))
    assert result.returncode == 0
    assert "CAUTIOUS_ALL:" in result.stdout
    assert "@cautious — reads {cautious}" in result.stdout
    assert result.stderr == ""


def test_discovery_module_lists_cases(tmp_path: Path) -> None:
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n% @expect sat\n")
    result = run_module("discovery", str(tmp_path / "encodings"))
    assert result.returncode == 0
    assert "self-contained" in result.stdout
    assert result.stderr == ""


def test_solvers_module_prints_the_determination(tmp_path: Path) -> None:
    program = write(tmp_path / "p.lp", "a. #show a/0.\n")
    result = run_module("solvers", "DEFAULT", str(program))
    assert result.returncode == 0
    assert "ConsistentWitness" in result.stdout
    assert result.stderr == ""


def test_module_usage_error_exits_2() -> None:
    result = run_module("expectation")  # missing the file argument
    assert result.returncode == 2
    assert "usage" in result.stderr
