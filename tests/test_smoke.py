"""That the package imports at all, which is the one failure every other test would report as
something else."""

import re

import elenctic


def test_package_imports() -> None:
    # That a version is there and is one, rather than which one it is. The number lives in exactly
    # one place — `elenctic.__version__`, which the build backend reads and which the README's pin
    # example is checked against — and restating it here made a fourth statement of it whose only
    # effect was that cutting a release edited a test named for something else.
    # Deliberately loose about what follows the three numbers: a pre-release or a development
    # version is a legitimate thing to build, and a test named for whether the package imports
    # must not fail the day one is cut.
    assert re.match(r"\d+\.\d+\.\d+", elenctic.__version__), elenctic.__version__
