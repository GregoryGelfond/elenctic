"""Corpus hygiene (spec §5): orphan libraries (the §1 backstop) and undeclared-solver cases,
computed over the resolved ``#include`` closure. This is the pure detection (``inspect_corpus``);
the ``--strict`` warn/error dial lives at the CLI (``test_cli_strict``)."""

from pathlib import Path

from elenctic.discovery import Corpus, HygieneReport, inspect_corpus

_CASE = "% @expect sat\n% @model {{ ok }}\n{solver}ok.\n#show ok/0.\n"


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _case(declared: bool = True) -> str:
    """A minimal passing case; ``declared`` toggles the ``@elenctic solver clingo`` declaration."""
    return _CASE.format(solver="% @elenctic solver clingo\n" if declared else "")


def test_inspect_corpus_returns_cases_and_a_hygiene_report(tmp_path: Path) -> None:
    write(tmp_path / "case.lp", _case())
    corpus = inspect_corpus(tmp_path)
    assert isinstance(corpus, Corpus)
    assert isinstance(corpus.hygiene, HygieneReport)
    assert [c.path.name for c in corpus.cases] == ["case.lp"]
    assert corpus.hygiene.clean  # solver declared, no orphans


def test_an_orphan_library_is_flagged(tmp_path: Path) -> None:
    write(tmp_path / "case.lp", _case())
    write(tmp_path / "orphan.lp", "never(used).\n")  # contract-free, no case #includes it
    hygiene = inspect_corpus(tmp_path).hygiene
    assert (tmp_path / "orphan.lp") in hygiene.orphan_libraries
    assert not hygiene.clean


def test_an_included_library_is_not_an_orphan(tmp_path: Path) -> None:
    write(tmp_path / "lib" / "facts.lp", "p(1..3).\n")
    write(
        tmp_path / "case.lp",
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingo\n"
        '#include "lib/facts.lp".\nok :- p(1).\n#show ok/0.\n',
    )
    assert inspect_corpus(tmp_path).hygiene.orphan_libraries == ()


def test_a_transitively_included_library_is_not_an_orphan(tmp_path: Path) -> None:
    # case -> b -> c: c is reached only transitively, yet it is a live dependency, not an orphan.
    write(tmp_path / "c.lp", "r(1).\n")
    write(tmp_path / "b.lp", '#include "c.lp".\nq :- r(1).\n')
    write(
        tmp_path / "case.lp",
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingo\n"
        '#include "b.lp".\nok :- q.\n#show ok/0.\n',
    )
    assert inspect_corpus(tmp_path).hygiene.orphan_libraries == ()


def test_a_diamond_include_counts_shared_once_not_an_orphan(tmp_path: Path) -> None:
    # case -> a and case -> b, both -> shared: clingo loads shared once, and it is a live
    # dependency (in `used`), so it is not an orphan.
    write(tmp_path / "shared.lp", "base(1).\n")
    write(tmp_path / "a.lp", '#include "shared.lp".\npa :- base(1).\n')
    write(tmp_path / "b.lp", '#include "shared.lp".\npb :- base(1).\n')
    write(
        tmp_path / "case.lp",
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingo\n"
        '#include "a.lp".\n#include "b.lp".\nok :- pa, pb.\n#show ok/0.\n',
    )
    assert inspect_corpus(tmp_path).hygiene.orphan_libraries == ()


def test_a_commented_out_include_does_not_shield_an_orphan(tmp_path: Path) -> None:
    # A `% #include "x"` is commented out (not a live dependency), so x is still an orphan — the
    # line-anchored scan errs toward over-reporting (the safe direction for a warn-only check).
    write(
        tmp_path / "case.lp",
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingo\n"
        '% #include "orphan.lp".\nok.\n#show ok/0.\n',
    )
    write(tmp_path / "orphan.lp", "never(used).\n")
    assert (tmp_path / "orphan.lp") in inspect_corpus(tmp_path).hygiene.orphan_libraries


def test_a_block_commented_include_does_not_shield_an_orphan(tmp_path: Path) -> None:
    # A `%* ... *%` block-commented #include is invisible to clingo, so the orphan is still flagged.
    # The closure reads clingo's authoritative parse (sources), not a text regex that would match
    # into the block comment and silently absorb the orphan (the safe direction: never hide one).
    write(
        tmp_path / "case.lp",
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingo\n"
        '%*\n#include "orphan.lp".\n*%\nok.\n#show ok/0.\n',
    )
    write(tmp_path / "orphan.lp", "never(used).\n")
    assert (tmp_path / "orphan.lp") in inspect_corpus(tmp_path).hygiene.orphan_libraries


def test_an_undeclared_solver_case_is_flagged(tmp_path: Path) -> None:
    write(tmp_path / "case.lp", _case(declared=False))  # no @elenctic solver → defaults to clingo
    hygiene = inspect_corpus(tmp_path).hygiene
    assert (tmp_path / "case.lp") in hygiene.undeclared_solvers
    assert not hygiene.clean


def test_a_declared_solver_case_is_not_flagged_undeclared(tmp_path: Path) -> None:
    write(tmp_path / "case.lp", _case(declared=True))
    assert inspect_corpus(tmp_path).hygiene.undeclared_solvers == ()


def test_orphan_libraries_are_in_deterministic_sorted_order(tmp_path: Path) -> None:
    # The walk is sorted(rglob), so records are reported in path order, not filesystem/creation
    # order (the HygieneReport docstring's "deterministic" claim).
    write(tmp_path / "case.lp", _case())
    for name in ("z_lib.lp", "a_lib.lp", "m_lib.lp"):  # created out of lexical order
        write(tmp_path / name, "never(used).\n")
    orphans = [path.name for path in inspect_corpus(tmp_path).hygiene.orphan_libraries]
    assert orphans == ["a_lib.lp", "m_lib.lp", "z_lib.lp"]


def test_a_single_file_target_finds_no_orphans(tmp_path: Path) -> None:
    case = write(tmp_path / "case.lp", _case())
    write(tmp_path / "orphan.lp", "never(used).\n")  # a sibling, but the target is one file
    assert inspect_corpus(case).hygiene.orphan_libraries == ()  # no tree to walk for orphans


def test_a_cyclic_include_terminates_and_both_libraries_are_live(tmp_path: Path) -> None:
    # clingo resolves a #include cycle by loading each file once (no hang, no error), so the orphan
    # check inherits that termination for free — both libraries are live dependencies, not orphans.
    write(tmp_path / "a.lp", '#include "b.lp".\nx.\n')
    write(tmp_path / "b.lp", '#include "a.lp".\ny.\n')
    write(
        tmp_path / "case.lp",
        "% @expect sat\n% @model { ok }\n% @elenctic solver clingo\n"
        '#include "a.lp".\nok :- x, y.\n#show ok/0.\n',
    )
    assert inspect_corpus(tmp_path).hygiene.orphan_libraries == ()
