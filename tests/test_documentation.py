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

_README = (Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")


def test_the_release_a_reader_is_told_to_pin_is_this_release() -> None:
    # The one line in the README that goes stale by the project doing nothing wrong: cutting a
    # release moves the version, and the example keeps naming whichever release was current when it
    # was written — which still reads as current, and is the version a reader will actually pin. It
    # named v0.1.1 through two releases, so the reader following it got the tree from before a
    # containment fix. Asserted as a set, so a second example added later cannot go stale quietly.
    pinned = set(re.findall(r'tag = "(v[^"]+)"', _README))
    assert pinned == {f"v{elenctic.__version__}"}, (
        "the README's pin example must name this release; the version is single-sourced from "
        "elenctic.__version__, and cutting a release moves both"
    )
