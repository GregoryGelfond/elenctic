"""What the README states about this package, checked against the package.

The README is what everyone arriving reads and is enforced by nothing that runs, so a sentence in it
stays true only for as long as somebody remembers to move it. What is held here is the part that is
mechanically checkable — a claim naming a value the package also holds — and the boundary is worth
stating plainly: a green run here does not mean the README is right, only that it does not
contradict the package about the few things it names in the package's own terms.

The README is read from the source tree rather than from the installed package, which is where it
is and where an edit to it lands. It is not shipped inside the wheel, and these tests are not
either.
"""

import re
from pathlib import Path

import elenctic
from elenctic.solvers import TIME_BUDGET

_README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


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
