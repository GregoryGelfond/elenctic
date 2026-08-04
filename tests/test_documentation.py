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
import re
from pathlib import Path

import elenctic
from elenctic.solvers import TIME_BUDGET

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_CHANGELOG = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

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
    # Both documents at once, and asserted whole rather than one name at a time, so a reader of a
    # failure sees every name that has come adrift rather than the first.
    mentioned = sorted(
        {name for text in (_README, _CHANGELOG) for name in _DOTTED_NAME.findall(text)}
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
