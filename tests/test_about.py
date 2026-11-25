import re
import tomllib
from email.utils import parseaddr
from importlib.metadata import metadata
from pathlib import Path

from elenctic.about import YEAR, Package, package

ROOT = Path(__file__).parent.parent
LICENSE = ROOT / "LICENSE"
COPYRIGHT_LINE = re.compile(r"^Copyright \(c\) (\d{4}) (.+)$", re.MULTILINE)


def test_the_package_reads_its_version_license_and_holder_from_its_metadata() -> None:
    installed = metadata("elenctic")
    assert package() == Package(
        installed["Version"],
        installed["License-Expression"],
        parseaddr(installed["Author-email"])[0],
        YEAR,
    )


def test_the_author_is_declared_with_a_name_and_an_email() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert declared["project"]["authors"] == [
        {"name": "Gregory Gelfond", "email": "gregory_gelfond@fastmail.com"}
    ]
    assert metadata("elenctic")["Author-email"] == "Gregory Gelfond <gregory_gelfond@fastmail.com>"


def test_the_license_is_mit_and_the_holder_is_the_author() -> None:
    read = package()
    assert (read.license, read.holder) == ("MIT", "Gregory Gelfond")


def test_the_year_and_holder_are_those_of_the_copyright_line_of_the_license_file() -> None:
    lines = COPYRIGHT_LINE.findall(LICENSE.read_text(encoding="utf-8"))
    assert lines == [(str(package().year), package().holder)]


LICENSE_EXPRESSION_SINCE = "1.27"
"""The first hatchling to write `License-Expression`, which `package` reads."""


def test_every_build_takes_a_hatchling_that_writes_the_license_expression() -> None:
    declared = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert declared["build-system"]["requires"] == [f"hatchling>={LICENSE_EXPRESSION_SINCE}"]
    recipe = (ROOT / "recipe" / "recipe.yaml").read_text(encoding="utf-8")
    assert f"    - hatchling >={LICENSE_EXPRESSION_SINCE}\n" in recipe


def test_the_recipe_tests_the_version_its_metadata_gives() -> None:
    recipe = (ROOT / "recipe" / "recipe.yaml").read_text(encoding="utf-8")
    assert "      - elenctic --version\n" in recipe


def test_the_image_build_is_given_every_file_the_package_metadata_names() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    named = {project["readme"], *project["license-files"]}
    copied = {
        word
        for line in (ROOT / "Containerfile").read_text(encoding="utf-8").splitlines()
        if line.startswith("COPY ") and "--from" not in line
        for word in line.split()[1:-1]
    }
    assert named <= copied
