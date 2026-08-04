"""That the package imports at all, which is the one failure every other test would report as
something else."""

import elenctic


def test_package_imports() -> None:
    assert elenctic.__version__ == "0.2.0"
