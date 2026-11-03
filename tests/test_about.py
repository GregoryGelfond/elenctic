import re
from importlib.metadata import metadata
from pathlib import Path

from elenctic.about import YEAR, Package, package

LICENSE = Path(__file__).parent.parent / "LICENSE"
COPYRIGHT_LINE = re.compile(r"^Copyright \(c\) (\d{4}) (.+)$", re.MULTILINE)


def test_the_package_reads_its_version_licence_and_holder_from_its_metadata() -> None:
    installed = metadata("elenctic")
    assert package() == Package(
        installed["Version"], installed["License-Expression"], installed["Author"], YEAR
    )


def test_the_licence_is_mit_and_the_holder_is_the_author() -> None:
    read = package()
    assert (read.licence, read.holder) == ("MIT", "Gregory Gelfond")


def test_the_year_and_holder_are_those_of_the_copyright_line_of_the_licence_file() -> None:
    lines = COPYRIGHT_LINE.findall(LICENSE.read_text(encoding="utf-8"))
    assert lines == [(str(package().year), package().holder)]
