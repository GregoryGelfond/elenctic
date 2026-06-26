"""``discovery.discover`` — the content-keyed corpus walk.

A ``.lp`` file is a **case** iff it carries a known elenctic tag (the collection predicate),
else a **library** (an ``#include`` target). ``discover(target)`` runs a single file (issue #3) or
walks a directory. The solver is **declared** (``@elenctic solver``, default ``clingo``), never read
from a filename. The program under test is the case file + its resolved ``#include``s, and the
preconditions + the theory-presence gate are enforced over that **resolved program**
(``check_program``), not the case-file text. Deterministic; loud on a precondition violation
(``DiscoveryError``), a malformed contract (``ContractError``), or a bad ``#include``
(``ProgramError``).
"""

from pathlib import Path

import pytest

from elenctic.discovery import DiscoveryError, discover
from elenctic.expectation import ContractError, Sat
from elenctic.program import ProgramError


def write(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` (creating parents) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


# --- entry points: a single file (issue #3) and a directory walk ---


def test_single_file_with_a_contract_is_one_case(tmp_path: Path) -> None:
    case_file = write(tmp_path / "feasible.lp", "% @expect sat\n% @model { a }\na. #show a/0.\n")
    (case,) = discover(case_file)
    assert case.path == case_file
    assert case.solver == "clingo"  # undeclared → the default
    assert isinstance(case.expectation, Sat)
    assert case.files == (case_file,)  # the loader resolves any #include; files is just the case


def test_explicit_contract_free_file_is_loud(tmp_path: Path) -> None:
    # A named target the user asked to run is never a silent no-op.
    library = write(tmp_path / "lib.lp", "task(1..3).\n")
    with pytest.raises(DiscoveryError, match=r"not a case|no .*contract"):
        discover(library)


def test_nonexistent_target_is_loud(tmp_path: Path) -> None:
    # A named target that does not exist tests nothing; a silent green would hide a typo or a moved
    # file — the cardinal sin for a testing tool (loud over silent).
    with pytest.raises(DiscoveryError, match=r"no such file or directory"):
        discover(tmp_path / "typo.lp")


def test_unreadable_lp_entry_in_the_walk_is_a_friendly_error(tmp_path: Path) -> None:
    # rglob matches a directory (or broken symlink) named *.lp; reading it must be a friendly
    # DiscoveryError, never a raw OSError traceback (the friendly-errors principle).
    write(tmp_path / "real.lp", "% @expect sat\n")
    (tmp_path / "weird.lp").mkdir()  # a DIRECTORY named *.lp, matched by rglob("*.lp")
    with pytest.raises(DiscoveryError, match=r"cannot read"):
        discover(tmp_path)


def test_directory_walk_collects_cases_and_skips_libraries(tmp_path: Path) -> None:
    write(tmp_path / "lib" / "sched.lp", "task(1..3).\n")  # a library: no known tag
    write(tmp_path / "feasible.lp", "% @expect sat\n% @model { ok }\nok :- task(1).\n#show ok/0.\n")
    write(tmp_path / "infeasible.lp", "% @expect unsat\n:- not task(9).\ntask(1).\n")
    cases = discover(tmp_path)
    assert sorted(c.path.name for c in cases) == ["feasible.lp", "infeasible.lp"]  # lib skipped


def test_non_lp_files_are_ignored(tmp_path: Path) -> None:
    write(tmp_path / "case.lp", "% @expect sat\n")
    write(tmp_path / "notes.txt", "% @expect sat\n")  # not .lp → not walked
    assert [c.path.name for c in discover(tmp_path)] == ["case.lp"]


def test_discovery_is_deterministic_and_sorted(tmp_path: Path) -> None:
    write(tmp_path / "b.lp", "% @expect sat\n")
    write(tmp_path / "a" / "c.lp", "% @expect sat\n")
    write(tmp_path / "a.lp", "% @expect sat\n")
    paths = [c.path for c in discover(tmp_path)]
    assert paths == sorted(paths)  # Path-sorted (sorted rglob), deterministic
    assert paths == [c.path for c in discover(tmp_path)]  # idempotent across calls


# --- the declared solver ---


def test_declared_solver_is_used(tmp_path: Path) -> None:
    case = write(
        tmp_path / "c.lp",
        "% @expect sat\n% @elenctic solver clingcon\n&dom { 1..3 } = x.\n#show.\n",
    )
    assert discover(case)[0].solver == "clingcon"


# --- dependencies via #include, and the gates over the RESOLVED program ---


def test_include_is_resolved_by_the_loader_not_enumerated(tmp_path: Path) -> None:
    write(tmp_path / "lib" / "facts.lp", "p(1). p(2).\n")
    case = write(
        tmp_path / "c.lp", '% @expect sat\n#include "lib/facts.lp".\nq :- p(1).\n#show q/0.\n'
    )
    (discovered,) = discover(case)
    assert discovered.files == (case,)  # one file; the include resolves at solve/inspect time


def test_r1_theory_in_an_included_library_under_clingo_is_loud(tmp_path: Path) -> None:
    # The theory gate reads the RESOLVED program: a theory atom hidden in a library + a forgotten
    # declaration → loud, no verdict (the silent-mis-solve the gate exists to prevent).
    write(tmp_path / "lib" / "thy.lp", "&dom { 1..3 } = x.\n")
    case = write(tmp_path / "c.lp", '% @expect sat\n#include "lib/thy.lp".\n#show.\n')
    with pytest.raises(DiscoveryError, match=r"theory atom.*clingo"):
        discover(case)


def test_r1_theory_in_a_library_under_declared_clingcon_is_accepted(tmp_path: Path) -> None:
    write(tmp_path / "lib" / "thy.lp", "&dom { 1..3 } = x.\n")
    case = write(
        tmp_path / "c.lp",
        '% @expect sat\n% @elenctic solver clingcon\n#include "lib/thy.lp".\n#show.\n',
    )
    assert discover(case)[0].solver == "clingcon"


def test_r2_optimization_gate_reads_the_resolved_program(tmp_path: Path) -> None:
    # #minimize lives in the included library, yet @cost's optimization gate is satisfied (it scans
    # the resolved program, not the case text). The pre-migration text scan would false-loud here.
    write(tmp_path / "lib" / "opt.lp", "#minimize { 1,a : a }.\n")
    case = write(
        tmp_path / "c.lp", '% @expect sat\n% @cost { 0 }\n#include "lib/opt.lp".\n#show a/0.\n'
    )
    (discovered,) = discover(case)
    assert isinstance(discovered.expectation, Sat)


def test_r2_cost_over_maximize_in_a_library_is_loud(tmp_path: Path) -> None:
    # The GATING silent-miscompile guard, now over the resolved program: a #maximize in the library
    # would be missed by a case-text scan, skipping the guard and mis-costing @cost.
    write(tmp_path / "lib" / "opt.lp", "#maximize { 1,a : a }.\n")
    case = write(
        tmp_path / "c.lp", '% @expect sat\n% @cost { 1 }\n#include "lib/opt.lp".\n#show a/0.\n'
    )
    with pytest.raises(DiscoveryError, match=r"#maximize|negated|not supported"):
        discover(case)


def test_contrary_precondition_reads_the_resolved_shown_vocabulary(tmp_path: Path) -> None:
    # #show lives in the library; the no-query's contrary (-reachable) is absent from the resolved
    # shown vocabulary → loud. (Reads the resolved program, not the case text.)
    write(tmp_path / "lib" / "enc.lp", "#show reachable/1.\n")
    case = write(
        tmp_path / "c.lp", '% @expect sat\n% @query no { reachable(x) }\n#include "lib/enc.lp".\n'
    )
    with pytest.raises(DiscoveryError, match=r"-reachable|contrary|shown"):
        discover(case)


def test_a_bad_include_is_a_friendly_program_error(tmp_path: Path) -> None:
    # inspect() runs at discovery (before any solve), so a missing #include surfaces as a friendly
    # ProgramError with provenance, never a raw clingo traceback at solve time.
    case = write(tmp_path / "c.lp", '% @expect sat\n#include "nope.lp".\n')
    with pytest.raises(ProgramError, match=r"nope\.lp|#include|resolve"):
        discover(case)


# --- provenance & the shown vocabulary (read from the resolved program) ---


def test_contract_source_and_files_are_the_case_path(tmp_path: Path) -> None:
    case = write(tmp_path / "c.lp", "% @expect sat\n")
    (discovered,) = discover(case)
    assert discovered.contract_source == case
    assert discovered.files == (case,)


def test_notes_survive_discovery(tmp_path: Path) -> None:
    case = write(tmp_path / "c.lp", "% @expect sat\n% @note the budget forces a detour\n")
    (discovered,) = discover(case)
    assert discovered.expectation.notes == ("the budget forces a detour",)


def test_malformed_contract_propagates_a_sourced_error(tmp_path: Path) -> None:
    case = write(tmp_path / "bad.lp", "% @model { a }\n")  # no @expect
    with pytest.raises(ContractError, match=r"bad\.lp"):
        discover(case)


def test_shown_vocabulary_is_sign_and_arity_aware(tmp_path: Path) -> None:
    case = write(tmp_path / "c.lp", "% @expect sat\n#show reachable/1.\n#show -reachable/1.\n")
    assert discover(case)[0].shown == frozenset({("reachable", 1), ("-reachable", 1)})


def test_bare_show_shows_nothing(tmp_path: Path) -> None:
    case = write(tmp_path / "c.lp", "% @expect sat\n#show.\n")
    assert discover(case)[0].shown == frozenset()


def test_query_unknown_with_a_wrong_arity_contrary_is_loud(tmp_path: Path) -> None:
    # The arity-blind silent-wrong-PASS closure: a ground @query unknown whose contrary is #shown
    # at the WRONG arity (a typo) is unobservable, so it must be LOUD, never certified PASS by
    # defaulting to unknown. The shown vocabulary is keyed by (name, arity).
    case = write(
        tmp_path / "typo.lp",
        "% @expect sat\n% @query unknown { reachable(c) }\n"
        "reachable(a). -reachable(c).\n#show reachable/1.\n#show -reachable/2.\n",
    )
    with pytest.raises(DiscoveryError, match=r"-reachable/1"):
        discover(case)
