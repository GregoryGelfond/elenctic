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
    with pytest.raises((DiscoveryError, Exception)) as caught:
        discover(case)
    assert "outside" in str(caught.value)

    _write(tmp_path / "corpus/sibling.lp", _LIBRARY)
    ok = _write(tmp_path / "corpus/good.lp", _CASE.format(include='"sibling.lp"'))
    assert len(discover(ok)) == 1, "a sibling library is inside the named file's own directory"
