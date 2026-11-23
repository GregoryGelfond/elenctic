from collections.abc import Callable
from pathlib import Path

import clingo.ast
import pytest

COLOR_VARIABLES = ("NO_COLOR", "FORCE_COLOR", "PYTHON_COLORS", "TERM")


@pytest.fixture(autouse=True)
def _environment_asks_nothing_about_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whatever the developer's environment says about color, a test starts without it."""
    for name in COLOR_VARIABLES:
        monkeypatch.delenv(name, raising=False)


class _BuildsNoNodes:
    """Clingo's foreign-function library, refusing the one call that builds a node."""

    def __init__(self, library: object) -> None:
        self._library = library

    def __getattr__(self, name: str) -> object:
        if name == "clingo_ast_build":
            message = "a clingo node was built rather than copied and changed in place"
            raise AssertionError(message)
        return getattr(self._library, name)


@pytest.fixture(autouse=True)
def _no_clingo_node_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test builds a clingo node, by a constructor or `AST.update`; `tree.renamed` says why."""
    monkeypatch.setattr(clingo.ast, "_lib", _BuildsNoNodes(vars(clingo.ast)["_lib"]))


type Link = Callable[[Path, Path], None]


@pytest.fixture
def link() -> Link:
    """Make a symbolic link at a path to a target, or skip where links cannot be made."""

    def made(at: Path, target: Path) -> None:
        try:
            at.symlink_to(target, target_is_directory=target.is_dir())
        except OSError as error:  # Windows without the privilege to make links
            pytest.skip(f"symbolic links cannot be made here: {error}")

    return made
