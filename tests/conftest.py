"""Suite-wide pytest configuration: the one marker this project defines, declared here because the
suite runs under ``--strict-markers`` and an undeclared marker is an error rather than a note."""

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "spike: confirms a clingo/clingcon behaviour elenctic relies on",
    )
