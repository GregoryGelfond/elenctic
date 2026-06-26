import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "spike: confirms a clingo/clingcon behaviour elenctic relies on",
    )
