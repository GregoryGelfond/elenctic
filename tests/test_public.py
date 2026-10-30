import importlib

import aspnext


def test_every_name_in_all_is_defined() -> None:
    assert all(hasattr(aspnext, name) for name in aspnext.__all__)


def test_all_is_sorted_and_free_of_duplicates() -> None:
    assert sorted(set(aspnext.__all__)) == sorted(aspnext.__all__)


def test_the_query_kernel_is_public() -> None:
    assert {"Answer", "singleton_answer", "Literal", "Assumption", "solve"} <= set(aspnext.__all__)


def test_the_package_reexports_what_its_modules_define() -> None:
    query = importlib.import_module("aspnext.query")
    assert aspnext.Answer is query.Answer
