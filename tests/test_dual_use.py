"""Dual-use: each inspectable pipeline-stage module runs under ``python -m``.

The contract-parsing, discovery, run-derivation, and solve stages are each runnable standalone as a
debugging aid (``python -m elenctic.<stage> …``), in addition to being importable. The sub-component
and pure-data modules (``query``/``terms``/``result``/``checks``) are *not* given a ``__main__`` — a
standalone entry there would be artificial; their behaviour surfaces through the stage modules and
the ``elenctic`` console script (``cli``). Neither is ``streams``, for a different reason: it is not
a stage at all but what the five entry points *ask* on their way in, so there is nothing there to
inspect — what it does is visible only as the streams the caller is then left holding.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from elenctic.outcome import ExitStatus
from support import without_standard_error

# Every stage that runs standalone. Each refuses an empty command line with a usage line and status
# 2, which is the one behaviour all four share and the one the pair of tests below is about.
_STAGES = ("expectation", "run", "discovery", "solvers")


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _command(module: str, *args: str) -> list[str]:
    # -W error::RuntimeWarning turns the runpy "found in sys.modules" re-import warning into a
    # failure, so the lazy-__init__ fix (no eager submodule load) is pinned: any regression aborts.
    return [sys.executable, "-W", "error::RuntimeWarning", "-m", f"elenctic.{module}", *args]


def run_module(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(_command(module, *args), capture_output=True, text=True, check=False)


def test_expectation_module_prints_the_parsed_contract(tmp_path: Path) -> None:
    contract = write(tmp_path / "c.lp", "% @expect sat\n% @model { a }\n")
    result = run_module("expectation", str(contract))
    assert result.returncode == ExitStatus.OK
    assert "Sat" in result.stdout
    assert result.stderr == ""  # pristine: no runpy re-import warning (the lazy-__init__ contract)


def test_run_module_prints_the_derived_plan(tmp_path: Path) -> None:
    contract = write(tmp_path / "c.lp", "% @expect sat\n% @cautious { a }\n")
    result = run_module("run", str(contract))
    assert result.returncode == ExitStatus.OK
    assert "CAUTIOUS_ALL:" in result.stdout
    assert "@cautious ({ a }) — reads {cautious}" in result.stdout  # the claim, not just the tag
    assert result.stderr == ""


def test_the_run_module_does_not_print_a_corpus_escape_to_a_terminal(tmp_path: Path) -> None:
    # This entry point renders the same corpus-chosen subject the CLI's --explain does, through a
    # frame of its own, and it writes to a terminal like any other. The subject rides a quoted
    # string term, which carries whatever the author put between the quotes all the way here.
    erases_the_line = "\x1b[2K"
    contract = write(
        tmp_path / "c.lp",
        f'% @expect sat\n% @cautious {{ p("x{erases_the_line}y") }}\np("x{erases_the_line}y").\n',
    )
    result = run_module("run", str(contract))
    assert result.returncode == ExitStatus.OK
    assert erases_the_line not in result.stdout, "the escape reached the reader's terminal intact"
    assert "\\x1b[2K" in result.stdout, "and nothing was silently dropped"


def test_discovery_module_lists_cases(tmp_path: Path) -> None:
    write(tmp_path / "encodings/g/e.lp", "#show p/0.\n% @expect sat\n")
    result = run_module("discovery", str(tmp_path / "encodings"))
    assert result.returncode == ExitStatus.OK
    assert "e.lp [clingo]" in result.stdout  # the discovered case file and its (default) solver
    assert result.stderr == ""


def test_solvers_module_prints_the_solve_outcome(tmp_path: Path) -> None:
    program = write(tmp_path / "p.lp", "a. #show a/0.\n")
    result = run_module("solvers", "DEFAULT", str(program))
    assert result.returncode == ExitStatus.OK
    assert "ConsistentWitness" in result.stdout, "the arm the solve settled"
    assert "Conclusion." in result.stdout, "and how its search ended, which is half the answer"
    assert result.stderr == ""


@pytest.mark.parametrize("stage", _STAGES)
def test_module_usage_error_exits_2(stage: str) -> None:
    result = run_module(stage)  # missing the file argument
    assert result.returncode == ExitStatus.USER_FAULT
    assert "usage" in result.stderr
    assert result.stdout == "", "the payload stream carries the inspection, never the refusal"


@pytest.mark.parametrize("stage", _STAGES)
def test_a_refusal_stays_off_the_payload_when_there_is_no_standard_error(stage: str) -> None:
    # A closed descriptor 2 is not a redirected one: this language leaves ``sys.stderr`` as
    # ``None``, and ``print`` writes to *standard output* when it is told to write to that. So the
    # stream carrying the inspection — the thing a reader is piping into something else — receives
    # ``usage: python -m elenctic....`` instead, on the one run that produced no inspection at all.
    #
    # The console entry answers this on its first line. These four are the same kind of program and
    # owe the same guarantee, which is why the rule is asked rather than restated here.
    finished = without_standard_error(_command(stage))

    assert finished.returncode == ExitStatus.USER_FAULT
    assert finished.stdout == "", (
        "the usage line landed in the payload stream when standard error was gone"
    )


def test_a_stage_that_does_its_work_survives_having_no_standard_error(tmp_path: Path) -> None:
    # The refusal above is the *short* path through a stage with no standard error. This is the long
    # one, and it reaches further: a solve captures the solver's own diagnostics by taking a copy of
    # descriptor 2 and flushing the stream, both of which fail outright where the descriptor is gone
    # and the stream was never built. Before these entries asked for a standard error, this run was
    # not a wrong answer — it was no answer at all.
    program = write(tmp_path / "p.lp", "a. #show a/0.\n")

    finished = without_standard_error(_command("solvers", "DEFAULT", str(program)))

    assert finished.returncode == ExitStatus.OK
    assert "ConsistentWitness" in finished.stdout, "the inspection this entry point exists for"
