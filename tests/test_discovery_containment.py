"""A case may only load files from the corpus it belongs to.

``#include`` resolution is clingo's, and clingo will open whatever path it is given. A corpus is
untrusted input — it is cloned, or it arrives in a pull request — so an unconstrained include lets
a case read any file the process can open, and elenctic's own diagnostics then publish what it
read: a deliberately false ``@expect unsat`` renders the witnessing model, which is the included
file's content.

The corpus root is the containment boundary, not the case's own directory. Reaching *upward* is
ordinary and supported — a scenario file including a shared encoding several levels up is the usual
layout — so the rule is that every resolved source stays under the root the run was pointed at.
"""

from pathlib import Path

import pytest

from elenctic.discovery import Case, discover, inspect_corpus
from elenctic.expectation import Sat
from elenctic.harness import run_case
from elenctic.outcome import ErrorKind, error_kind

# `_origins` is past `program.__all__`: it reads the file paths out of one line of clingo's
# diagnostic text, and that reading is what containment rests on. Reached directly because a
# whole run only shows whether the refusal happened, not which line it was derived from.
from elenctic.program import Boundary, ContainmentError, ProgramError, Unrestricted, _origins
from elenctic.run import Mode
from elenctic.solvers import run_clingo, solve

_LIBRARY = "fact(1).\n"
_CASE = "% @expect sat\n% @count  1\n\n#include {include}.\nfact(2).\n#show fact/1.\n"


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_case_may_include_a_library_anywhere_under_the_corpus_root(tmp_path: Path) -> None:
    # The layout the rule must not break: a case deep in the tree reaching up and across to a
    # shared encoding. This is how a real corpus is organised, so containment is worthless if it
    # costs this.
    _write(tmp_path / "encodings/shared.lp", _LIBRARY)
    _write(
        tmp_path / "scenarios/a/b/case.lp",
        _CASE.format(include='"../../../encodings/shared.lp"'),
    )
    cases = discover(tmp_path)
    assert len(cases) == 1, "an upward include inside the corpus is ordinary, not an escape"


def test_a_case_may_not_include_a_file_outside_the_corpus_root(tmp_path: Path) -> None:
    # The attack: the corpus reads a file it was never pointed at. Left unchecked, the content
    # reaches the terminal through elenctic's own failure diagnostics.
    outside = _write(tmp_path / "outside/private.lp", 'confidential_marker("wxyz").\n')
    root = tmp_path / "corpus"
    _write(root / "case.lp", _CASE.format(include=f'"{outside}"'))

    corpus = inspect_corpus(root)
    assert corpus.cases == (), "a case escaping the root must not be run"
    assert len(corpus.unrunnable) == 1, "it is reported against its own file, not silently dropped"
    _path, fault = corpus.unrunnable[0]
    message = str(fault)
    assert "private.lp" in message, "the diagnostic must name the file that escaped"
    assert "confidential_marker" not in message, (
        "naming the path is the diagnostic; repeating what was read would be the disclosure"
    )


def test_a_relative_escape_is_refused_like_an_absolute_one(tmp_path: Path) -> None:
    # ../ climbing past the root is the same escape wearing a relative path.
    _write(tmp_path / "outside/secret.lp", 'secret("do not read me").\n')
    root = tmp_path / "corpus"
    _write(root / "deep/case.lp", _CASE.format(include='"../../outside/secret.lp"'))

    corpus = inspect_corpus(root)
    assert corpus.cases == ()
    assert len(corpus.unrunnable) == 1


def test_a_symlink_out_of_the_corpus_is_refused(tmp_path: Path) -> None:
    # Containment is decided on the resolved path, so a link is not a way around it.
    outside = _write(tmp_path / "outside/secret.lp", 'secret("do not read me").\n')
    root = tmp_path / "corpus"
    root.mkdir(parents=True, exist_ok=True)
    (root / "link.lp").symlink_to(outside)
    _write(root / "case.lp", _CASE.format(include='"link.lp"'))

    corpus = inspect_corpus(root)
    assert corpus.cases == ()
    assert len(corpus.unrunnable) == 1


def test_an_explicitly_named_case_is_rooted_at_its_own_directory(tmp_path: Path) -> None:
    # Naming one file gives no directory to take as the root, so the file's own is used. A sibling
    # library is reachable; the tree above it is not.
    _write(tmp_path / "outside/secret.lp", 'secret("do not read me").\n')
    case = _write(tmp_path / "corpus/case.lp", _CASE.format(include='"../outside/secret.lp"'))
    with pytest.raises(ContainmentError, match=r"outside the corpus") as caught:
        discover(case)
    # The rule is at its narrowest here and the reader did not choose it: running the directory
    # above admits the very same case. So the diagnostic has to say where the boundary came from
    # and how to widen it, or it reads as elenctic refusing a case it ran a moment ago.
    said = str(caught.value)
    assert "you named a single case" in said
    assert "run the corpus directory" in said

    _write(tmp_path / "corpus/sibling.lp", _LIBRARY)
    ok = _write(tmp_path / "corpus/good.lp", _CASE.format(include='"sibling.lp"'))
    assert len(discover(ok)) == 1, "a sibling library is inside the named file's own directory"


def test_the_narrower_boundary_is_explained_only_where_it_is_narrower(tmp_path: Path) -> None:
    # The companion, and it is what keeps the sentence honest: pointed at a directory the boundary
    # is the one the reader chose, so there is nothing to explain and the clause must not appear.
    outside = _write(tmp_path / "outside/secret.lp", 'secret("do not read me").\n')
    root = tmp_path / "corpus"
    _write(root / "case.lp", _CASE.format(include=f'"{outside}"'))
    (_path, fault) = inspect_corpus(root).unrunnable[0]
    assert "outside the corpus" in str(fault)
    assert "you named a single case" not in str(fault)


def test_an_escaping_include_that_fails_to_parse_discloses_nothing_from_inside_it(
    tmp_path: Path,
) -> None:
    # The channel the sources check cannot reach: a parse that *fails* inside the escaping file
    # returns no sources to judge, while clingo's own diagnostic names the file, how far into it
    # the parse got, and which characters it objected to — an existence-and-shape oracle over
    # anything the process can read, driven from a corpus.
    broken = "ok(1).\nok(2).\nconfidential_marker this is not asp\n"
    outside = _write(tmp_path / "outside/secret.lp", broken)
    root = tmp_path / "corpus"
    _write(root / "case.lp", _CASE.format(include=f'"{outside}"'))

    (_path, fault) = inspect_corpus(root).unrunnable[0]
    escaped = str(fault)
    assert "secret.lp" in escaped, "naming the escaping path is the diagnostic"
    assert "confidential_marker" not in escaped
    assert "secret.lp:3" not in escaped, "nor how far into it the parse got"
    assert "syntax error" not in escaped, "nor what the solver made of its contents"

    # The control, and the test says nothing without it: the SAME broken file inside the root does
    # get clingo's diagnostic, coordinates and all. Without this the assertions above would hold
    # over an implementation that never publishes a parse diagnostic at all.
    inside_root = tmp_path / "corpus2"
    _write(inside_root / "lib/secret.lp", broken)
    _write(inside_root / "case.lp", _CASE.format(include='"lib/secret.lp"'))
    (_path, published) = inspect_corpus(inside_root).unrunnable[0]
    assert "secret.lp:3:" in str(published), "a file inside the corpus is diagnosed in full"
    assert "syntax error" in str(published)


@pytest.mark.parametrize(
    "directory",
    [
        pytest.param("run-2026-08-06T12:30:00", id="a-timestamp"),
        pytest.param("v1:2:3", id="a-version"),
        pytest.param("a:b", id="a-colon-and-a-letter"),
    ],
)
def test_a_corpus_path_that_looks_like_a_coordinate_still_gets_its_own_diagnostic(
    tmp_path: Path, directory: str
) -> None:
    # The containment rule reads file names out of clingo's diagnostic, which is `path:line:col`, so
    # a path that itself contains `:N:M` is where that reading goes wrong — and it is an ordinary
    # thing for a directory to be named: a timestamp, a version. The first two rows fail against a
    # rule that takes one guess at the split; the third does not, and is kept to say so, because the
    # test that used to stand here used only that shape and so passed over every rule there is,
    # including the one that was wrong.
    root = tmp_path / directory / "corpus"
    _write(root / "case.lp", "% @expect sat\n% @count 1\nthis is not asp\n")
    (_path, fault) = inspect_corpus(root).unrunnable[0]
    assert "syntax error" in str(fault), "the case's own fault is still reported in full"
    assert "outside the corpus" not in str(fault), "and it is not accused of reading anything"


def test_a_corpus_cannot_choose_where_the_diagnostic_is_split(tmp_path: Path) -> None:
    # The other side of the same ambiguity, and the reason one guess cannot be the rule: the text
    # being split is the corpus author's. A committed directory named for a time, and an include
    # spelled through it, put the `:N:M` wherever they like — here so that the shortest split lands
    # *inside* the corpus and the escape reads as ordinary.
    _write(tmp_path / "outside/secret.lp", "ok(1).\nconfidential_marker this is not asp\n")
    root = tmp_path / "corpus"
    (root / "12:30:00").mkdir(parents=True)
    _write(root / "case.lp", _CASE.format(include='"12:30:00/../../outside/secret.lp"'))

    (_path, fault) = inspect_corpus(root).unrunnable[0]
    said = str(fault)
    assert "secret.lp" in said, "the escaping path is named"
    assert "confidential_marker" not in said
    assert "syntax error" not in said, "and the solver's account of it is not"


def test_a_relative_escape_that_fails_to_parse_is_refused_like_one_that_parses(
    tmp_path: Path,
) -> None:
    # `..` climbing out of the corpus, on a file that does *not* parse — so the sources check never
    # sees it and the diagnostic is all there is. Containment is decided on the resolved path, and
    # it has to be: a parts-prefix test on the text reads `root/deep/../../outside` as under `root`,
    # which is the shape that made the absolute-path fixtures beside this one insufficient.
    _write(tmp_path / "outside/secret.lp", "ok(1).\nbroken syntax here\n")
    root = tmp_path / "corpus"
    _write(root / "deep/case.lp", _CASE.format(include='"../../outside/secret.lp"'))

    (_path, fault) = inspect_corpus(root).unrunnable[0]
    assert "outside the corpus" in str(fault)
    assert "syntax error" not in str(fault), "the solver's account of the escaping file is withheld"


def test_a_sibling_whose_name_extends_the_roots_is_outside_it(tmp_path: Path) -> None:
    # Containment compares resolved *parts*, never text. Under a prefix test `…/corpus-private`
    # reads as under `…/corpus`, and every other fixture here puts the escaping file in a sibling
    # whose name shares no prefix with the root — so a prefix test would have passed all of them.
    _write(tmp_path / "corpus-private/keys.lp", 'secret("do not read me").\n')
    root = tmp_path / "corpus"
    _write(root / "case.lp", _CASE.format(include='"../corpus-private/keys.lp"'))

    corpus = inspect_corpus(root)
    assert corpus.cases == ()
    assert "outside the corpus" in str(corpus.unrunnable[0][1])


def test_the_narrower_boundary_is_explained_whichever_frame_refuses(tmp_path: Path) -> None:
    # One rule, two frames — which one notices is decided by whether the escaping file happens to
    # parse, and a reader has no use for that difference. The explanation of where the boundary came
    # from has to be on both paths, or the same mistake gets a better diagnostic on the luckier one.
    _write(tmp_path / "outside/parses.lp", "fact(9).\n")
    _write(tmp_path / "outside/broken.lp", "ok(1).\nbroken syntax here\n")
    for name, include in (("a", '"../outside/parses.lp"'), ("b", '"../outside/broken.lp"')):
        case = _write(tmp_path / f"corpus/{name}.lp", _CASE.format(include=include))
        with pytest.raises(ContainmentError, match=r"outside the corpus") as caught:
            discover(case)
        assert "you named a single case" in str(caught.value), f"{name}: on both paths"


def test_one_containment_rule_is_one_locus(tmp_path: Path) -> None:
    # And the same fact in the register a consumer reads. Filed by the frame that noticed, these
    # would be `program` or `discovery` depending on the offending file's syntax — one mistake in
    # two buckets, which is the shape this package already fixed once for a broken `#include`.
    _write(tmp_path / "outside/parses.lp", "fact(9).\n")
    _write(tmp_path / "outside/broken.lp", "ok(1).\nbroken syntax here\n")
    _write(tmp_path / "corpus/a.lp", _CASE.format(include='"../outside/parses.lp"'))
    _write(tmp_path / "corpus/b.lp", _CASE.format(include='"../outside/broken.lp"'))

    faults = [fault for _path, fault in inspect_corpus(tmp_path / "corpus").unrunnable]
    assert len(faults) == 2, "one that parses, one that does not"
    assert {error_kind(fault) for fault in faults} == {ErrorKind.CONTAINMENT}


# A library that resolves, parses, and then will not ground — so it is past both frames above by the
# time clingo objects to it. The rule clingo echoes back carries the marker, which is what makes the
# ground diagnostic a disclosure and not merely a coordinate.
_UNGROUNDABLE = 'confidential_marker("wxyz").\np(X) :- confidential_marker(Y).\n'
_LOADS = "#include {include}.\nfact(2).\n"


def test_a_discovered_case_carries_the_boundary_it_was_found_under(tmp_path: Path) -> None:
    # The link the two guards below cannot hold, because each builds the case it runs. Unless
    # discovery puts the boundary ON the case, every case the product actually runs carries none,
    # the solve frame is asked to enforce nothing, and both of those guards stay green over a corpus
    # with no rule in force at all — measured, with the whole suite passing.
    _write(tmp_path / "corpus/lib.lp", _LIBRARY)
    _write(tmp_path / "corpus/a.lp", _CASE.format(include='"lib.lp"'))
    (found,) = discover(tmp_path / "corpus")
    assert found.boundary == Boundary((tmp_path / "corpus").resolve())

    # A named file is rooted at its own directory instead, carrying the flag that has the refusal
    # explain why the boundary is the narrower one. Both shapes, because the walk builds the value
    # in two places and a case that reached the solver with the wrong one would be refused for a
    # rule nobody stated.
    _write(tmp_path / "solo/lib.lp", _LIBRARY)
    named = _write(tmp_path / "solo/case.lp", _CASE.format(include='"lib.lp"'))
    (only,) = discover(named)
    assert only.boundary == Boundary((tmp_path / "solo").resolve(), from_named_file=True)


def test_a_ground_fault_inside_an_escaping_library_discloses_nothing_from_it(
    tmp_path: Path,
) -> None:
    # The third channel, and neither frame above reaches it: a program whose every include resolves
    # — so the sources check is satisfied and the parse frame is long past — and which then fails to
    # GROUND. clingo names the escaping file, the coordinates it objected to, and the rule it was
    # reading when it did. So the boundary has to be known where the *solve* reads that diagnostic,
    # for the same reason it had to be known where the parse read its own.
    _write(tmp_path / "outside/secret.lp", _UNGROUNDABLE)
    root = tmp_path / "corpus"
    case = _write(root / "case.lp", _LOADS.format(include='"../outside/secret.lp"'))

    with pytest.raises(
        ContainmentError, match=r"secret\.lp, which is outside the corpus"
    ) as caught:
        run_clingo(Mode.ENUM_ALL, files=(case,), within=Boundary(root.resolve()))
    said = str(caught.value)
    assert "secret.lp" in said, "naming the escaping path is the diagnostic"
    assert "confidential_marker" not in said, "what was read inside it is not"
    assert "unsafe" not in said, "nor the solver's account of what is wrong with it"
    assert "secret.lp:2" not in said, "nor how far into it the grounding got"

    # The control, and the test says nothing without it: the same ungroundable library INSIDE the
    # root is diagnosed in full, coordinates and all. Without this every assertion above would hold
    # over a facade that had simply stopped reporting ground faults.
    inside = tmp_path / "corpus2"
    _write(inside / "lib/secret.lp", _UNGROUNDABLE)
    contained = _write(inside / "case.lp", _LOADS.format(include='"lib/secret.lp"'))
    with pytest.raises(ProgramError, match=r"cannot run the program: .*secret\.lp:\d") as published:
        run_clingo(Mode.ENUM_ALL, files=(contained,), within=Boundary(inside.resolve()))
    assert not isinstance(published.value, ContainmentError), "this one reaches past nothing"
    assert "secret.lp:2:" in str(published.value), "a file inside the corpus is diagnosed in full"
    assert "unsafe" in str(published.value)


def test_the_boundary_a_case_was_discovered_under_reaches_its_solve(tmp_path: Path) -> None:
    # The rule above is only in force if the boundary gets there, and a corpus cannot demonstrate
    # that it does: every case reaching the solver has already had its sources judged, so a breach
    # arrives only through a tree that changed between the two moments. The case is therefore built
    # rather than discovered — which is that changed tree, stated directly — and what is held here
    # is the thread from the boundary a case belongs to down to the frame that reads the solver's
    # diagnostic.
    _write(tmp_path / "outside/secret.lp", _UNGROUNDABLE)
    root = tmp_path / "corpus"
    path = _write(root / "case.lp", _LOADS.format(include='"../outside/secret.lp"'))
    bounded = Case(
        path, "clingo", Sat(expect_line=1), Unrestricted(), boundary=Boundary(root.resolve())
    )
    with pytest.raises(ContainmentError, match="outside the corpus"):
        run_case(bounded)

    # And the other direction, because a rule asserted only one way cannot detect its own
    # weakening: a case carrying NO boundary states no rule, and gets the solver's account in full.
    # That is the reading a caller who assembled the files themselves already has from
    # `inspect(files, within=None)`, and it is what makes the refusal above attributable to the
    # boundary rather than to anything else about the fixture.
    unbounded = Case(path, "clingo", Sat(expect_line=1), Unrestricted())
    with pytest.raises(ProgramError, match=r"cannot run the program: .*secret\.lp:\d") as unheld:
        run_case(unbounded)
    assert not isinstance(unheld.value, ContainmentError), "no boundary, no containment rule"
    assert "confidential_marker" in str(unheld.value), "and so nothing is withheld"


def test_a_boundary_refuses_a_root_that_is_not_already_resolved(tmp_path: Path) -> None:
    # Containment compares a RESOLVED candidate against this path, so an unresolved root fails that
    # comparison for every file in the corpus — including the case's own. Measured before the
    # refusal existed: a corpus reached through a symlink was told its own case file was outside it,
    # which reads as an escape and is elenctic's fault entirely.
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(ValueError, match=r"resolved path"):
        Boundary(tmp_path / "link")

    # The other direction, or the guard cannot tell a refusal from a function that refuses
    # everything: the same directory named as it resolves is accepted, and so is a path that does
    # not exist, since resolving one normalises it without requiring it to be there.
    assert Boundary((tmp_path / "link").resolve()).root == (tmp_path / "real").resolve()
    assert Boundary(tmp_path / "nothing/here").root == tmp_path / "nothing/here"


def test_a_diagnostic_beginning_with_its_coordinate_names_no_origin() -> None:
    # `Path("")` is `Path(".")`, which exists and resolves to the working directory — so a line
    # leaving nothing before its coordinate would offer the directory elenctic happens to be run
    # from as a file the solver opened, and a corpus that never named it would be refused for
    # reaching outside itself.
    assert _origins(":1:1: error: a line that begins with its coordinate") == []
    # And the ordinary shape still resolves, so the guard above is not passing on a broken reader.
    assert _origins(f"{__file__}:1:1: error: something") == [Path(__file__)]


def test_the_flags_a_solve_takes_cannot_be_passed_positionally() -> None:
    # `project` and `within` are adjacent, both optional, and differently typed. Passed positionally
    # with `budget` omitted, a boundary lands in `project` — where it is truthy, so the run projects
    # and states no containment rule at all. A type checker rejects it; nothing at run time did, and
    # this is the curated entry point, where a consumer without one meets it.
    with pytest.raises(TypeError):
        solve("clingo", Mode.ENUM_ALL, "a.", (), 30.0, True)  # type: ignore[misc]


def test_the_theory_backend_withholds_a_parse_diagnostic_too(tmp_path: Path) -> None:
    # The theory facade's region is the wider one — clingcon does its own parsing inside it — so on
    # that backend an escaping file that will not PARSE is refused by the solve-side seam, where on
    # the plain backend the same file never gets that far. Measured rather than inferred from the
    # nesting, because which failures a region encloses is exactly what a reader guesses wrong.
    pytest.importorskip("clingcon")
    from elenctic.solvers import run_clingcon

    _write(tmp_path / "outside/secret.lp", "ok(1).\nconfidential_marker this is not asp\n")
    root = tmp_path / "corpus"
    case = _write(root / "case.lp", _LOADS.format(include='"../outside/secret.lp"'))
    with pytest.raises(
        ContainmentError, match=r"secret\.lp, which is outside the corpus"
    ) as caught:
        run_clingcon(Mode.ENUM_ALL, files=(case,), within=Boundary(root.resolve()))
    assert "secret.lp" in str(caught.value), "the escaping path is named"
    assert "confidential_marker" not in str(caught.value), "and its contents are not"
    assert "syntax error" not in str(caught.value), "nor the solver's account of them"
