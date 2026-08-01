"""A fault names the right owner, and a remedy is only offered when it is the remedy.

elenctic divides faults by whose they are: a ``ProgramError`` is the corpus author's to fix, a
``HarnessError`` is ours. The division is carried by exception type, and the types come from clingo,
which reports almost everything through one channel — so the division is only as good as what each
guarded region does with what it catches.

Two ways it goes wrong, and both mislead rather than merely inconvenience. A fault attributed to the
wrong owner sends someone to fix code that is not broken. And a fault attributed to the right owner
but explained with the wrong *remedy* is worse than no explanation, because it is specific enough to
act on.
"""

import os
from pathlib import Path

import pytest

from elenctic.program import ProgramError, inspect
from elenctic.run import Mode
from elenctic.solvers import run_clingo


def _write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


def test_an_unresolvable_include_is_the_one_fault_that_names_include_paths(
    tmp_path: Path,
) -> None:
    # The remedy is real here, so it is offered here.
    case = _write(tmp_path, "case.lp", '#include "no_such_library.lp".\n')
    with pytest.raises(ProgramError) as caught:
        inspect((case,))
    assert "#include" in str(caught.value)


@pytest.mark.parametrize("body", ['#show "text" : p.\np.\n', "#show 42 : p.\np.\n", "p( :- q.\n"])
def test_a_fault_that_is_not_about_includes_does_not_blame_includes(
    tmp_path: Path, body: str
) -> None:
    # Every one of these is the author's to fix, so ProgramError is the right register. None of them
    # has anything to do with #include, and being told to check include paths sends the author to
    # read a line that is not there.
    case = _write(tmp_path, "case.lp", body)
    with pytest.raises(ProgramError) as caught:
        inspect((case,))
    assert "#include" not in str(caught.value), "a remedy is offered only when it is the remedy"


def test_a_term_nested_past_the_walk_says_so(tmp_path: Path) -> None:
    # elenctic's own AST walk has a depth limit, and a program can exceed it. The author is the one
    # who can act, so it stays a ProgramError — but the remedy is to flatten the term, and saying
    # "check your #include paths" instead is a specific instruction to do something useless.
    chain = "1" + "+1" * 2_000
    case = _write(tmp_path, "deep.lp", f"p(X) :- X = {chain}.\n#show p/1.\n")
    with pytest.raises(ProgramError) as caught:
        inspect((case,))
    message = str(caught.value)
    assert "nested" in message, "the diagnostic must name what is actually wrong"
    assert "#include" not in message


def test_a_file_name_that_is_not_utf8_is_the_corpus_author_s_fault(tmp_path: Path) -> None:
    # clingo encodes the path strictly, so a file whose *name* carries a non-UTF-8 byte raises
    # UnicodeEncodeError — a sibling of UnicodeDecodeError, not a subclass, so it escaped the
    # region entirely and was reported as an elenctic bug. It is the corpus's, and renaming fixes
    # it.
    raw = os.fsencode(tmp_path) + b"/caf\xe9.lp"
    with open(raw, "wb") as handle:
        handle.write(b"p.\n#show p/0.\n")
    case = Path(os.fsdecode(raw))

    with pytest.raises(ProgramError) as caught:
        inspect((case,))
    assert "UTF-8" in str(caught.value)


def test_an_objective_that_grounds_away_is_the_program_s_fault_not_ours(tmp_path: Path) -> None:
    # `has_optimization` is syntactic — a #minimize node is present. Whether the *ground* program
    # has an objective is a different fact, and an objective over an empty domain grounds away. The
    # cost vector is then missing for a reason the corpus explains, so claiming elenctic's own
    # precondition is broken accuses the wrong party and volunteers a bug that is not there.
    case = _write(tmp_path, "empty_objective.lp", "#minimize { X : p(X) }.\nq.\n#show q/0.\n")
    assert inspect((case,)).has_optimization, "the objective is syntactically present"

    with pytest.raises(ProgramError) as caught:
        run_clingo(Mode.OPTIMAL, files=(case,))
    assert "ground" in str(caught.value).lower()
