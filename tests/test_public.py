import annotationlib
import importlib
import typing
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import elenctic

ROOT = Path(__file__).parent.parent


def test_every_name_in_all_is_defined() -> None:
    assert all(hasattr(elenctic, name) for name in elenctic.__all__)


def test_all_is_sorted_and_free_of_duplicates() -> None:
    assert sorted(set(elenctic.__all__)) == sorted(elenctic.__all__)


def test_the_query_kernel_is_public() -> None:
    assert {"Answer", "Literal", "Assumption", "solve"} <= set(elenctic.__all__)


def test_a_literal_is_answered_by_the_one_function_that_answers_a_query() -> None:
    assert "answer" in elenctic.__all__
    assert not hasattr(elenctic, "singleton_answer")
    assert not hasattr(importlib.import_module("elenctic.query"), "singleton_answer")


def test_the_package_reexports_what_its_modules_define() -> None:
    query = importlib.import_module("elenctic.query")
    assert elenctic.Answer is query.Answer


@pytest.mark.parametrize("name", ["mgu", "Unifier"])
@pytest.mark.parametrize("document", ["docs/reference/reference.md", "CHANGELOG.md"])
def test_the_unifier_is_public_and_is_documented(name: str, document: str) -> None:
    assert name in elenctic.__all__
    assert name in (ROOT / document).read_text(encoding="utf-8")


def _ours(annotation: object) -> bool:
    return str(getattr(annotation, "__module__", "")).startswith("elenctic.")


def _elenctic_types(annotation: object) -> Iterator[object]:
    """Yield each class and alias of elenctic that `annotation` names, through the aliases."""
    if isinstance(annotation, typing.ForwardRef):
        yield from _elenctic_types(annotation.evaluate())
        return
    if isinstance(annotation, typing.TypeAliasType):
        if _ours(annotation):
            yield annotation
        yield from _elenctic_types(annotation.__value__)
        return
    if isinstance(annotation, type) and _ours(annotation):
        yield annotation
    for part in typing.get_args(annotation):
        yield from _elenctic_types(part)


def _signature_types(function: Callable[..., object]) -> Iterator[object]:
    yield from _annotated(function)


def _annotated(owner: object) -> Iterator[object]:
    """Yield the elenctic types in the annotations of `owner`, and of its bases when a class."""
    for each in owner.__mro__ if isinstance(owner, type) else (owner,):
        for annotation in annotationlib.get_annotations(
            each, format=annotationlib.Format.FORWARDREF
        ).values():
            yield from _elenctic_types(annotation)


def _member_types(member: object) -> Iterator[object]:
    match member:
        case property(fget=getter) if getter is not None:
            yield from _signature_types(getter)
        case classmethod() | staticmethod():
            yield from _signature_types(member.__func__)
        case _ if callable(member) and not isinstance(member, type):
            yield from _signature_types(member)


def _public_types(exported: object) -> Iterator[object]:
    """Yield the elenctic types that the public signatures of an exported name mention."""
    if isinstance(exported, typing.TypeAliasType):
        yield from _elenctic_types(exported.__value__)
    elif isinstance(exported, type):
        yield from _annotated(exported)
        for name, member in vars(exported).items():
            if not name.startswith("_"):
                yield from _member_types(member)
    elif callable(exported):
        yield from _signature_types(exported)


def _identity(item: object) -> tuple[str, str]:
    """Name an item by where it is defined, which survives a class being rebuilt by a decorator."""
    return str(getattr(item, "__module__", "")), str(getattr(item, "__qualname__", item))


def test_the_exported_names_are_closed_under_their_own_signatures() -> None:
    exported = {_identity(getattr(elenctic, name)) for name in elenctic.__all__}
    unnamed: dict[str, set[str]] = {}
    for name in elenctic.__all__:
        for used in _public_types(getattr(elenctic, name)):
            if _identity(used) not in exported:
                unnamed.setdefault(_identity(used)[1], set()).add(name)
    assert unnamed == {}


def test_the_walk_finds_a_type_that_a_signature_names_and_the_package_does_not_export() -> None:
    class Hidden:
        pass

    Hidden.__module__ = "elenctic.hidden"

    def question(_: Hidden) -> list[Hidden | None]:
        raise NotImplementedError

    assert set(_public_types(question)) == {Hidden}
