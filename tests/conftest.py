import pytest

COLOR_VARIABLES = ("NO_COLOR", "CLICOLOR", "CLICOLOR_FORCE", "FORCE_COLOR", "PYTHON_COLORS", "TERM")


@pytest.fixture(autouse=True)
def _environment_asks_nothing_about_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the developer's environment says about colour, a test starts without it."""
    for name in COLOR_VARIABLES:
        monkeypatch.delenv(name, raising=False)
