import importlib
from pathlib import Path

import pytest

import elenctic

ROOT = Path(__file__).parent.parent


def test_every_name_in_all_is_defined() -> None:
    assert all(hasattr(elenctic, name) for name in elenctic.__all__)


def test_all_is_sorted_and_free_of_duplicates() -> None:
    assert sorted(set(elenctic.__all__)) == sorted(elenctic.__all__)


def test_the_query_kernel_is_public() -> None:
    assert {"Answer", "singleton_answer", "Literal", "Assumption", "solve"} <= set(elenctic.__all__)


def test_the_package_reexports_what_its_modules_define() -> None:
    query = importlib.import_module("elenctic.query")
    assert elenctic.Answer is query.Answer


@pytest.mark.parametrize("name", ["mgu", "Unifier"])
@pytest.mark.parametrize("document", ["docs/reference/reference.md", "CHANGELOG.md"])
def test_the_unifier_is_public_and_is_documented(name: str, document: str) -> None:
    assert name in elenctic.__all__
    assert name in (ROOT / document).read_text(encoding="utf-8")
