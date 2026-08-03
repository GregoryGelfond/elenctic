"""The packaged schema: what the document promises, checked against what the package produces.

The schema file is the published half of the machine-readable report — for most consumers it *is*
the documentation — so it is checked here as an artifact in its own right rather than trusted to
have been written correctly. Three things can go wrong with it, and each has a test. It can be an
invalid schema, in which case a consumer's generator refuses it before ever seeing a document. It
can disagree with the document the package actually emits, in either direction: a field the schema
does not know, or a field it requires and nothing writes. And it can drift from the vocabularies it
claims to enumerate, which is what a consumer meets as a value their own decoder rejects on a
document that is perfectly well-formed.

The vocabularies are checked in two ways because they grow in two ways. A **closed** one is
enumerated in the schema and gaining a member costs a version bump, so the test asserts the schema's
list and the package's enumeration are the same set — nothing weaker would notice a member added on
one side. An **open** one is typed as a string and gaining a value costs nothing, so what the test
asserts instead is that every value this version can emit appears in the prose that documents the
known ones, since prose is the only thing a reader has there and it is the first thing to rot.

The schema is read through the package's own resources — the same lookup the command line prints
from — so the two cannot come to read different files.
"""

import json
from copy import deepcopy
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import elenctic
from elenctic.cli import main, run_corpus
from elenctic.json_report import SCHEMA_VERSION, as_json, schema_text
from elenctic.outcome import ErrorKind, HygieneKind, Invocation, Scope, Severity
from elenctic.result import Conclusion, Verdict
from elenctic.solvers import TIME_BUDGET

# A corpus chosen so that one run fills all three registers at once: a case that passes, a case that
# fails and declares no solver (an observation), a file whose contract will not parse (an error),
# and a contract-free file nothing includes (a second observation, graded differently). A document
# validated against a corpus that only passes would say nothing about the shape of the other two
# registers, which are the ones a consumer has to branch on.
_PASSES = "% @elenctic solver clingo\n% @expect sat\n% @model { a }\na.\n#show a/0.\n"
_FAILS = "% @expect sat\n% @cautious { tea }\nbiscuit.\n#show biscuit/0.\n"
_MALFORMED = "% @expect banana\nb.\n"
_ORPHAN = "% a contract-free file nothing includes.\nhelper(1).\n"

# Every object the schema describes: what to call it, where one lives in a document, and where the
# schema describes it. All of them, because the field space is closed at each separately — a test
# that only reached the outermost object would pass against a schema that left the rest open.
_OBJECTS: list[tuple[str, tuple[str | int, ...], tuple[str | int, ...]]] = [
    ("the document", (), ()),
    ("the invocation", ("invocation",), ("$defs", "invocation")),
    ("the summary", ("summary",), ("$defs", "summary")),
    ("a case", ("cases", 0), ("$defs", "case")),
    ("a check", ("cases", 0, "checks", 0), ("$defs", "check")),
    ("an error", ("errors", 0), ("$defs", "error")),
    ("an observation", ("hygiene", 0), ("$defs", "hygiene")),
]
_OBJECT_IDS = [name for name, _, _ in _OBJECTS]

# A closed vocabulary and the enumeration it is the wire form of. The schema lists these, so the
# two are the same set or a consumer has been promised something untrue.
_CLOSED: list[tuple[tuple[str | int, ...], type[Enum]]] = [
    (("$defs", "verdict"), Verdict),
    (("$defs", "check", "properties", "conclusion"), Conclusion),
    (("$defs", "error", "properties", "scope"), Scope),
    (("$defs", "hygiene", "properties", "severity"), Severity),
]

# An open vocabulary and the enumeration it documents the current values of. The schema constrains
# these to `string`, so what is checked is the prose.
_OPEN: list[tuple[tuple[str | int, ...], type[Enum]]] = [
    (("$defs", "error", "properties", "kind"), ErrorKind),
    (("$defs", "hygiene", "properties", "kind"), HygieneKind),
]


def _schema() -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(schema_text())
    return parsed


def _validator() -> Draft202012Validator:
    return Draft202012Validator(_schema())


def _corpus(root: Path) -> Path:
    for name, text in (
        ("declared_pass", _PASSES),
        ("undeclared_fail", _FAILS),
        ("malformed", _MALFORMED),
        ("orphan_library", _ORPHAN),
    ):
        (root / f"{name}.lp").write_text(text, encoding="utf-8")
    return root


def _run(target: Path, *, strict: bool = False) -> dict[str, Any]:
    invocation = Invocation(target=target, strict=strict, budget=TIME_BUDGET, deadline=None)
    return as_json(run_corpus(invocation), invocation)


def _resolve(node: Any, path: tuple[str | int, ...]) -> Any:
    for step in path:
        node = node[step]
    return node


def _edited(document: dict[str, Any], path: tuple[str | int, ...], value: Any) -> dict[str, Any]:
    """A copy of the document with one value replaced, named by the path to it.

    A copy because the document is built once for the module: a test that mutated it in place would
    hand the next one a document that is no longer what a run produced.
    """
    copy = deepcopy(document)
    *parent, last = path
    _resolve(copy, tuple(parent))[last] = value
    return copy


@pytest.fixture(scope="module")
def document(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One document from one real run, with every register populated."""
    return _run(_corpus(tmp_path_factory.mktemp("corpus")))


def test_what_the_package_hands_back_is_the_file_that_ships() -> None:
    # Read by a route of its own, because every other test in this file reads the schema through
    # `schema_text` — so none of them would notice it starting to return something *rendered from*
    # the file instead of the file. That is not a hypothetical edit: re-parsing and re-dumping a
    # JSON document on the way out looks like tidying, and it escapes every test that compares the
    # output to the same function's return value. Someone who redirects `--print-schema` into their
    # own repository diffs these bytes against the published ones.
    packaged = Path(elenctic.__file__).parent / "schema" / f"output-v{SCHEMA_VERSION}.schema.json"

    assert schema_text() == packaged.read_text(encoding="utf-8")


def test_the_packaged_schema_is_itself_a_valid_schema() -> None:
    # Not a formality: a schema with a misspelled keyword validates everything, so a document could
    # pass every test below against a schema that is not checking anything.
    Draft202012Validator.check_schema(_schema())


def test_the_run_that_populates_every_register_populates_every_register(
    document: dict[str, Any],
) -> None:
    # The premise the tests below rest on. If this corpus ever stops producing all three, they would
    # go on passing while checking the shape of arrays that are empty.
    assert len(document["cases"]) == 2, "a case that passes and a case that fails"
    assert document["errors"], "a contract that will not parse"
    assert len(document["hygiene"]) == 2, "an orphan library and an undeclared solver"


@pytest.mark.parametrize("strict", [False, True], ids=["default", "strict"])
def test_a_document_a_real_run_produced_is_one_the_schema_accepts(
    tmp_path: Path, strict: bool
) -> None:
    # Both footings, because strictness is what grades an observation `error` and sets the flag the
    # invocation reports — values no default run puts in a document.
    _validator().validate(_run(_corpus(tmp_path), strict=strict))


def test_a_run_that_found_nothing_to_run_is_still_a_document_the_schema_accepts(
    tmp_path: Path,
) -> None:
    # The corpus-scoped register, which the fixture's corpus never reaches: no case produced a
    # verdict, so `cases` is empty and an error stands where they would have been. It is also the
    # only shape in which `source` is null rather than a file name.
    document = _run(tmp_path / "nowhere")

    _validator().validate(document)
    assert document["cases"] == []
    assert document["errors"], "a target that does not exist is a fault, not an empty corpus"


def test_the_version_is_one_number_that_three_places_agree_on(document: dict[str, Any]) -> None:
    # The document states it, the schema pins it, and the package defines it. A consumer choosing a
    # decoder by the first of those is entitled to the other two meaning the same thing.
    assert _schema()["properties"]["schema_version"]["const"] == SCHEMA_VERSION
    assert document["schema_version"] == SCHEMA_VERSION


@pytest.mark.parametrize(("described", "in_document", "in_schema"), _OBJECTS, ids=_OBJECT_IDS)
def test_a_field_nobody_promised_is_refused(
    document: dict[str, Any],
    described: str,
    in_document: tuple[str | int, ...],
    in_schema: tuple[str | int, ...],
) -> None:
    # The field space is closed, which is what makes adding a field a version bump rather than
    # something a consumer discovers.
    stray = deepcopy(document)
    _resolve(stray, in_document)["a_field_nobody_promised"] = "surprise"

    assert not _validator().is_valid(stray), (
        f"{described} accepted a field the schema does not know"
    )


@pytest.mark.parametrize(("described", "in_document", "in_schema"), _OBJECTS, ids=_OBJECT_IDS)
def test_every_field_the_package_writes_is_one_the_schema_requires(
    document: dict[str, Any],
    described: str,
    in_document: tuple[str | int, ...],
    in_schema: tuple[str | int, ...],
) -> None:
    # The other half of the closed field space, and the half a document cannot demonstrate: a schema
    # that merely permits a field lets a consumer be handed a record without it and still call the
    # document valid. Every field of every object here is required, so the two sets are the same set
    # — and making one optional later is a contract decision that has to come through this test.
    required = set(_resolve(_schema(), in_schema)["required"])

    assert required == set(_resolve(document, in_document)), (
        f"what the schema requires of {described} is not what the package writes"
    )


@pytest.mark.parametrize(
    ("path", "name"),
    [
        (("cases", 0, "verdict"), "PASS"),
        (("cases", 0, "checks", 0, "status"), "PASS"),
        (("cases", 0, "checks", 0, "conclusion"), "EXHAUSTED"),
        (("errors", 0, "scope"), "CASE"),
        (("hygiene", 0, "severity"), "WARNING"),
    ],
    ids=["verdict", "status", "conclusion", "scope", "severity"],
)
def test_a_closed_vocabulary_refuses_the_member_name_where_its_value_belongs(
    document: dict[str, Any], path: tuple[str | int, ...], name: str
) -> None:
    # Every closed vocabulary is written as its member's value, because that is what the ordinary
    # constructor reads back. The member's *name* is therefore the one wrong spelling a future edit
    # is most likely to reintroduce, and the schema has to be what refuses it.
    assert not _validator().is_valid(_edited(document, path, name))


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("errors", 0, "kind"), "a locus no version has named"),
        (("hygiene", 0, "kind"), "an observation no version has made"),
        (("cases", 0, "solver"), "a solver nobody has written"),
        (("cases", 0, "checks", 0, "tag"), "@a-tag-nobody-has-invented"),
    ],
    ids=["error-kind", "hygiene-kind", "solver", "tag"],
)
def test_an_open_vocabulary_accepts_a_value_this_version_never_heard_of(
    document: dict[str, Any], path: tuple[str | int, ...], value: str
) -> None:
    # The point of the open tier: a locus, an observation, a solver or a tag can be added without a
    # version bump, so a consumer pinned to this schema must not be made to reject the document.
    _validator().validate(_edited(document, path, value))


@pytest.mark.parametrize(
    ("path", "vocabulary"), _CLOSED, ids=[vocabulary.__name__ for _, vocabulary in _CLOSED]
)
def test_a_closed_vocabulary_is_exactly_what_the_package_can_emit(
    path: tuple[str | int, ...], vocabulary: type[Enum]
) -> None:
    # Both directions are failures and neither is caught by validating a document: a member the
    # schema omits makes a valid document invalid the first time it occurs, and a member the schema
    # invents promises a value nothing will ever write.
    assert set(_resolve(_schema(), path)["enum"]) == {member.value for member in vocabulary}


@pytest.mark.parametrize(
    ("path", "vocabulary"), _OPEN, ids=[vocabulary.__name__ for _, vocabulary in _OPEN]
)
def test_an_open_vocabulary_documents_every_value_this_version_can_emit(
    path: tuple[str | int, ...], vocabulary: type[Enum]
) -> None:
    # The schema cannot constrain these, so its prose is the whole of what a reader is given. A
    # value added to the package and not to the prose is undocumented rather than merely unlisted.
    described = _resolve(_schema(), path)["description"]
    for member in vocabulary:
        assert f"`{member.value}`" in described, f"{member.value!r} is emitted but not documented"


def test_printing_the_schema_writes_the_packaged_file_and_nothing_else(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Byte-for-byte, because someone redirecting this into a file is entitled to the file: a
    # description that had been parsed and re-rendered on the way out would say the same thing while
    # diffing against the published one as a change.
    status = main(["--print-schema"])

    captured = capsys.readouterr()
    assert status == 0
    assert captured.out == schema_text()
    assert captured.err == "", "nothing shares the stream the description is written to"


def test_printing_the_schema_asks_nothing_of_a_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # It is answered from the package alone, so it is answered before anything is looked for on
    # disk. A target that does not exist is a fault worth 2 on any other invocation, and someone
    # asking what the output looks like has no reason to have a corpus at all.
    status = main(["--print-schema", str(tmp_path / "no_such_corpus")])

    assert status == 0
    assert capsys.readouterr().out == schema_text()
