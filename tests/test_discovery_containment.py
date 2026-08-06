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

from elenctic.discovery import DiscoveryError, discover, inspect_corpus

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
    with pytest.raises(DiscoveryError, match=r"outside the corpus") as caught:
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
    assert "3:" not in escaped, "nor how far into it the parse got"
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


def test_a_corpus_path_containing_a_colon_still_gets_its_own_diagnostic(tmp_path: Path) -> None:
    # The containment rule reads the file name out of clingo's diagnostic, which is `path:line:col`,
    # so a path that itself contains a colon is where that reading could go wrong. It must not cost
    # an ordinary author their syntax error.
    root = tmp_path / "a:b" / "corpus"
    _write(root / "case.lp", "% @expect sat\n% @count 1\nthis is not asp\n")
    (_path, fault) = inspect_corpus(root).unrunnable[0]
    assert "syntax error" in str(fault), "the case's own fault is still reported in full"
    assert "outside the corpus" not in str(fault)
