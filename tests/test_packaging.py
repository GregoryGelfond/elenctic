"""What a built distribution actually contains — asked of the build backend, not of the source tree.

Two files elenctic ships are not code, and both are load-bearing. ``py.typed`` is what tells a type
checker this package is annotated; without it, every annotation in a package gated on ``mypy
--strict`` is invisible to whoever installs it, and the checker reports missing stubs rather than
anything about elenctic. ``schema/output-v*.schema.json`` is the published description of the
machine-readable report, which ``--print-schema`` reads back as a package resource.

Neither is reachable by a test that reads the source tree, and that is not a quibble: **the marker
was missing for the whole life of the project and no check here noticed**, because everything this
project runs — ruff, mypy, pytest — reads `src/`. A guarantee about what is *in a distribution* has
to be asked of a distribution.

The backend's own PEP 517 hooks are called directly rather than a build front-end being run. Three
reasons, in order of weight: the hooks are what a front-end would call anyway, so this tests the
configuration a real build uses; no front-end is in this environment and adding one would put a
whole isolated-build step in the way of a question about file inclusion; and it is fast, because
what makes ``python -m build`` slow is creating an environment and installing the backend into it,
neither of which is under test.
"""

import tarfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from hatchling.build import build_sdist, build_wheel

_ROOT = Path(__file__).resolve().parent.parent

# What has to be in a distribution and is not code. Named by the tail of the path, because a wheel
# lays the package out flat while an sdist keeps the source layout under a versioned directory.
_NOT_CODE = ("py.typed", "schema/output-v1.schema.json")


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, list[str]]]:
    """The names in a freshly built wheel and sdist.

    Built once for the module: the two hooks are the slow part of this file, and nothing here
    changes what they produce.

    The backend reads its configuration from the working directory, so the build happens with the
    process there and the directory is restored afterwards — a test that leaves the process
    somewhere else would silently change what every later test resolves a relative path against.
    """
    import os

    out = tmp_path_factory.mktemp("dist")
    was = Path.cwd()
    os.chdir(_ROOT)
    try:
        wheel = out / build_wheel(str(out))
        sdist = out / build_sdist(str(out))
    finally:
        os.chdir(was)
    with zipfile.ZipFile(wheel) as archive:
        wheel_names = archive.namelist()
    with tarfile.open(sdist) as archive:
        sdist_names = archive.getnames()
    yield {"wheel": wheel_names, "sdist": sdist_names}


@pytest.mark.parametrize("distribution", ["wheel", "sdist"])
@pytest.mark.parametrize("carried", _NOT_CODE)
def test_a_built_distribution_carries_the_files_that_are_not_code(
    built: dict[str, list[str]], distribution: str, carried: str
) -> None:
    # Both distributions, because they are assembled by different code paths and a consumer can be
    # handed either: a wheel is what `pip install elenctic` unpacks, and an sdist is what a build
    # from source starts from.
    #
    # The whole hazard is that these arrive by inclusion rather than by being written down: the
    # backend is told `packages = ["src/elenctic"]` and everything under it comes along. Narrowing
    # that to `*.py` — a plausible tidy-up — drops both files silently, leaves the package
    # importable, and breaks a consumer's type checking and `--print-schema` with nothing to say
    # why.
    assert any(name.endswith(carried) for name in built[distribution]), (
        f"the {distribution} does not carry {carried}. It ships by being under the package "
        f"directory the build backend was told to include, so anything that narrows that "
        f"inclusion drops it without breaking a single import"
    )


def test_the_build_backend_is_the_one_the_project_declares(built: dict[str, list[str]]) -> None:
    # This file asks the backend directly rather than running a front-end, which is only a fair
    # substitute while the backend it asks is the backend a front-end would use. Read from the
    # project's own build requirement, so the two cannot come apart.
    import tomllib

    with (_ROOT / "pyproject.toml").open("rb") as configuration:
        build_system = tomllib.load(configuration)["build-system"]
    assert build_system["build-backend"] == "hatchling.build", (
        "this asks hatchling what it would build; if the project has changed backend, it is asking "
        "the wrong one and its answer says nothing about what a real build produces"
    )
    assert built["wheel"], "the backend produced an empty wheel, so nothing below means anything"
