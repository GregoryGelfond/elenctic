"""What the two documents a consumer reads state about this package, checked against the package.

The README is what everyone arriving reads and the changelog is what everyone upgrading reads, and
both are enforced by nothing that runs — so a sentence in either stays true only for as long as
somebody remembers to move it. What is held here is the part that is mechanically checkable: a claim
naming a value or a name the package also holds. The boundary is worth stating plainly: a green run
here does not mean either document is right, only that it does not contradict the package about the
few things it names in the package's own terms.

Both are read from the source tree rather than from the installed package, which is where they are
and where an edit to them lands. Neither is shipped inside the wheel, and these tests are not
either.
"""

import importlib
import json
import re
from pathlib import Path

import elenctic
from elenctic.solvers import TIME_BUDGET

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_CHANGELOG = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
_CONTRIBUTING = (_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

# A dotted name under this package, written as code — `elenctic.outcome.ExitStatus` and the like.
# Anchored at `elenctic.` so that a backticked flag, path or scrap of ASP is not mistaken for one.
_DOTTED_NAME = re.compile(r"`(elenctic(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`")


def test_the_release_a_reader_is_told_to_pin_is_this_release() -> None:
    # The one line in the README that goes stale by the project doing nothing wrong: cutting a
    # release moves the version, and the example keeps naming whichever release was current when it
    # was written — which still reads as current, and is the version a reader will actually pin.
    # Asserted as a set, so a second example added later cannot go stale quietly either.
    pinned = set(re.findall(r'tag = "(v[^"]+)"', _README))
    assert pinned == {f"v{elenctic.__version__}"}, (
        "the README's pin example must name this release; the version is single-sourced from "
        "elenctic.__version__, and cutting a release moves both"
    )


def test_the_default_budget_the_readme_states_is_the_default_the_package_has() -> None:
    # Stated twice in the README — as the gloss on the flag, and as a value inside the one worked
    # machine-readable document — and held by nothing. The help does not have this problem, because
    # it interpolates the constant rather than quoting it; these two quote it.
    assert f"(default {TIME_BUDGET:g}s)" in _README, "the flag's gloss names the shipped default"
    assert f'"budget": {TIME_BUDGET}' in _README, "and so does the worked document"


def test_the_readme_does_not_keep_a_second_copy_of_the_exit_status_ladder() -> None:
    # The ladder has one home, `ExitStatus`, and `--help` is rendered from it. A copy here would be
    # a second thing to keep true, and it is exactly the copy that went stale: it is prose, so
    # nothing renders it and nothing checks it. What the README carries instead is a pointer.
    #
    # The document section is not a copy in this sense and is deliberately left alone: it states
    # the ladder as something a consumer computes *from the document*, which is a different claim
    # from what the process returns, and it is checked against the packaged description elsewhere.
    running = _README.split("## Running", 1)[1].split("### Machine-readable output", 1)[0]
    assert "elenctic --help" in running, "the invitation to read the canonical list"
    assert "3 an elenctic bug" not in running, "and not a second list beside it"


def test_every_name_the_documents_tell_a_reader_to_import_is_one_they_can() -> None:
    # A document naming a home sends a reader to it. When the name moves, the sentence keeps its
    # confident shape and stops being true, and the reader who follows it meets an ImportError with
    # nothing to say about where the thing went. That is not hypothetical: the entry announcing the
    # exit-status type named it under the console entry, which is not where it lives.
    #
    # Every document at once, and asserted whole rather than one name at a time, so a reader of a
    # failure sees every name that has come adrift rather than the first.
    mentioned = sorted(
        {
            name
            for text in (_README, _CHANGELOG, _CONTRIBUTING)
            for name in _DOTTED_NAME.findall(text)
        }
    )
    assert mentioned, "the pattern found nothing at all, which means it is no longer the pattern"
    adrift = [name for name in mentioned if not _is_a_home(name)]
    assert not adrift, (
        f"named in the README or the changelog, and not where the name says it lives: {adrift}. A "
        f"document that names a home sends a reader there; these have moved, or never existed"
    )


def _is_a_home(dotted: str) -> bool:
    """Whether ``dotted`` names this thing *where it lives* — rather than somewhere it merely
    happens to be visible.

    Importability is too weak a question to ask, and the defect that prompted this is why: the entry
    announcing the exit-status type named it under the console entry, which imports it, so the name
    resolved and the sentence was still wrong. A reader following it would find the thing and learn
    the wrong home for it, and the day the console entry stops importing it the sentence breaks with
    no warning.

    Two homes count, because this package has two legitimate ones: the module a thing is defined in,
    and the curated top-level surface, which exists precisely so that a consumer need not know the
    first. Anything else is an incidental re-export.

    A thing carrying no ``__module__`` — a plain constant — cannot be placed this way, and is taken
    at its word rather than guessed about.
    """
    try:
        importlib.import_module(dotted)
    except ImportError:
        pass
    else:
        return True  # a module is its own home
    module, _, attribute = dotted.rpartition(".")
    try:
        parent = importlib.import_module(module)
    except ImportError:
        return False
    if not hasattr(parent, attribute):
        return False
    if module == elenctic.__name__:
        return attribute in elenctic.__all__
    return getattr(getattr(parent, attribute), "__module__", module) == module


def test_the_readmes_library_example_runs_and_does_what_it_says(tmp_path: Path) -> None:
    """The worked example a consumer copies, run as written rather than read.

    This is the one block in either document that a reader will paste into their own project, and
    the release it demonstrates is the one this branch exists for — so "does it still import" is
    not the question. It is extracted from the README itself, so an edit to the prose is what runs.

    Run as a process, in a directory laid out the way the example assumes, because the example ends
    by leaving with a status and writes a file beside itself. Both are part of what it claims.
    """
    import subprocess
    import sys

    # Bounded by the next top-level heading rather than by a named one. It was named, and the
    # section it named later moved *above* this one — so the split stopped cutting anything and
    # the slice ran to the end of the file. It kept passing because exactly one Python block
    # happened to follow, which is an instrument that has silently stopped measuring.
    after = _README.split("## Using elenctic as a library", 1)[1]
    assert "\n## " in after, "the library section is last, so nothing bounds the slice below"
    section = after.split("\n## ", 1)[0]
    block = re.search(r"```python\n(.*?)```", section, re.S)
    assert block is not None, "the library section no longer holds a Python block to check"

    (tmp_path / "encodings").mkdir()
    (tmp_path / "encodings" / "case.lp").write_text(
        "% @elenctic solver clingo\n% @expect sat\n% @model { a }\na.\n#show a/0.\n",
        encoding="utf-8",
    )
    (tmp_path / "example.py").write_text(block.group(1), encoding="utf-8")

    done = subprocess.run(
        [sys.executable, "example.py"], cwd=tmp_path, capture_output=True, text=True
    )

    assert done.returncode == 0, f"the example did not leave cleanly: {done.stderr}"
    assert done.stderr == "", (
        "the section this example sits under opens by saying the library is silent, so anything "
        "the library wrote on its own would contradict the prose it is there to demonstrate"
    )
    assert done.stdout == "running case.lp\n  pass\n", (
        "the observer is what prints, and it prints as the run goes — a case announced when it is "
        "taken up and again when it is judged"
    )
    document = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert document["summary"]["passed"] == 1, "and the document it wrote reports the run"


def test_the_changelog_has_a_dated_section_for_the_version_being_shipped() -> None:
    """The link a release cut is most likely to break, and the one nothing was watching.

    Bumping ``__version__`` and forgetting to rename ``[Unreleased]`` ships a package whose
    changelog has no section for it — silently, because every other check here compares the version
    against the README rather than against the changelog. Cutting a release is exactly when a
    document goes stale, so the cut is what this holds.
    """
    dated = re.search(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", _CHANGELOG, re.M)
    assert dated is not None, "no dated release section at all"
    assert dated.group(1) == elenctic.__version__, (
        f"the newest dated section is {dated.group(1)} and this is {elenctic.__version__}; a "
        f"release whose changelog does not describe it tells an upgrader nothing"
    )
    assert f"\n[{elenctic.__version__}]: " in _CHANGELOG, (
        "and the link definition at the foot has to resolve, or the heading is a dead link"
    )
