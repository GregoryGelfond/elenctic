"""The packaged schema: what the document promises, checked against what the package produces.

The schema file is the published half of the machine-readable report — for most consumers it *is*
the documentation — so it is checked here as an artifact in its own right rather than trusted to
have been written correctly. Four things can go wrong with it, and each has tests. It can be an
invalid schema, or one that says nothing. It can disagree with the document the package emits, in
either direction: a field the schema does not know, or a field it requires and nothing writes. It
can drift from the vocabularies it claims to enumerate, which a consumer meets as a value their own
decoder rejects on a document that is perfectly well-formed. And it can *loosen* — a constraint
deleted or widened is invisible to any test that only asks whether a valid document still
validates, so the near-miss table below asks the other question, which is what the schema refuses.

The vocabularies are checked in two ways because they grow in two ways. A **closed** one is
enumerated in the schema and gaining a member costs a version bump, so the test asserts the schema's
list and the package's are the same set — nothing weaker would notice a member added on one side.
An **open** one is typed as a string and gaining a value costs nothing, so what the test asserts
instead is that every value this version can emit appears in the prose documenting the known ones,
since prose is all a reader has there and it is the first thing to rot.

Two guarantees here are about the document rather than about the schema, and they live here because
they are what a consumer's parser meets before any schema is consulted: that the report is JSON a
strict reader accepts, and that the description the command line prints is the file that ships.

The schema is read through the package's own resources — the same lookup the command line prints
from — so the two cannot come to read different files.
"""

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

import elenctic
from elenctic.cli import main
from elenctic.corpus import run_corpus
from elenctic.json_report import SCHEMA_VERSION, as_json, dumps, schema_text
from elenctic.outcome import ErrorKind, ExitStatus, HygieneKind, Invocation
from elenctic.registry import SOLVERS
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

# A closed vocabulary, where the schema enumerates it, and the values the package can write. The
# schema lists these, so the two are the same set or a consumer has been promised something untrue.
_CLOSED: list[tuple[str, tuple[str | int, ...], frozenset[str]]] = [
    ("verdict", ("$defs", "verdict"), frozenset(member.value for member in Verdict)),
    (
        "conclusion",
        ("$defs", "check", "properties", "conclusion"),
        frozenset(member.value for member in Conclusion),
    ),
    ("scope", ("$defs", "error", "properties", "scope"), frozenset({"corpus", "case"})),
    (
        "grade",
        ("$defs", "hygiene", "properties", "grade"),
        frozenset({"silent", "warning", "error"}),
    ),
]

# An open vocabulary and the values this version can put in it. The schema constrains these to
# `string`, so what is checked is the prose.
_OPEN: list[tuple[str, tuple[str | int, ...], frozenset[str]]] = [
    (
        "error kind",
        ("$defs", "error", "properties", "kind"),
        frozenset(member.value for member in ErrorKind),
    ),
    (
        "hygiene kind",
        ("$defs", "hygiene", "properties", "kind"),
        frozenset(member.value for member in HygieneKind),
    ),
    ("solver", ("$defs", "case", "properties", "solver"), SOLVERS),
]

# Documents that are wrong in a way no valid document can demonstrate. Each one exists because the
# constraint it violates is otherwise untested in the only direction that matters: a schema keeps
# accepting every valid document after the constraint is deleted, so what pins a constraint is a
# document it must refuse.
_NEAR_MISSES: list[tuple[str, tuple[str | int, ...], Any]] = [
    ("a case with no checks at all", ("cases", 0, "checks"), []),
    ("a claim on line zero", ("cases", 0, "checks", 0, "line"), 0),
    ("a line written as text", ("cases", 0, "checks", 0, "line"), "2"),
    ("an invocation that is not an object", ("invocation",), "everything"),
    ("cases that are not an array", ("cases",), 3),
    ("a negative count", ("summary", "total"), -1),
    ("a budget that is absent rather than a number", ("invocation", "budget"), None),
    ("a budget of no seconds at all", ("invocation", "budget"), 0),
    ("a budget written as text", ("invocation", "budget"), "60"),
    ("a deadline written as text", ("invocation", "deadline"), "60"),
    ("a deadline of no seconds at all", ("invocation", "deadline"), 0),
    # One row per count rather than one for the register they happen to sit in. A table that varies
    # which object is wrong but always picks the same field inside it leaves every sibling free: the
    # constraint on `total` was pinned and its five neighbours were each deletable with this whole
    # suite green. The fractional row is the one that catches a widening to `number`, and it has to
    # be fractional — an integral float validates against `"type": "integer"`.
    *(
        (described, ("summary", count), value)
        for count in ("total", "passed", "failed", "undecided", "errors", "hygiene")
        for described, value in (
            (f"a {count} count below zero", -1),
            (f"a {count} count that is not whole", 1.5),
        )
    ),
    ("a file name that is a number", ("errors", 0, "source"), 42),
    ("an observation about no file", ("hygiene", 0, "source"), None),
    ("an actionability answered with a word", ("errors", 0, "is_elenctic_bug"), "false"),
    ("a document claiming another version", ("schema_version",), 2),
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


def _run(
    target: Path,
    *,
    strict: bool = False,
    budget: float = TIME_BUDGET,
    deadline: float | None = None,
) -> dict[str, Any]:
    invocation = Invocation(target=target, strict=strict, budget=budget, deadline=deadline)
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


def _documented(field: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Whether a consumer meeting this field is told what it is — here, or where it points."""
    if field.get("description"):
        return True
    target = field.get("$ref")
    if target is None:
        return False
    pointed_at = _resolve(schema, tuple(target.removeprefix("#/").split("/")))
    return bool(pointed_at.get("description"))


@pytest.fixture(scope="module")
def document(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """One document from one real run, with every register populated.

    The run behind it prints its own report, so no test that captures output may be the first to
    ask for this fixture — the capture would pick up a summary line written on another test's
    behalf and accuse the wrong code of writing it.
    """
    return _run(_corpus(tmp_path_factory.mktemp("corpus")))


def test_what_the_package_hands_back_is_the_file_that_ships() -> None:
    # Read by a route of its own, because every other test in this file reads the schema through
    # `schema_text` — so none of them would notice it starting to return something *rendered from*
    # the file instead of the file. That is not a hypothetical edit: re-parsing and re-dumping a
    # JSON document on the way out looks like tidying, and it escapes every test that compares the
    # output to the same function's return value. Compared as bytes, since that is what someone
    # redirecting `--print-schema` into their own repository diffs against the published ones.
    packaged = Path(elenctic.__file__).parent / "schema" / f"output-v{SCHEMA_VERSION}.schema.json"

    assert schema_text().encode("utf-8") == packaged.read_bytes()


def test_the_packaged_schema_is_a_schema_this_dialect_can_read() -> None:
    # What this protects is a known keyword given a malformed value — `"enum": "pass"`, or a
    # `required` that is a string rather than a list — which would otherwise fail obscurely at the
    # first validation. It does *not* protect against a misspelled keyword: the metaschema does not
    # close its own field space, so `minItem` for `minItems` is a valid schema that constrains
    # nothing. What guards that is the near-miss table, which asks what the schema refuses.
    Draft202012Validator.check_schema(_schema())


def test_the_schema_declares_the_dialect_and_the_identity_it_is_published_under() -> None:
    # Neither is read by anything in this file — the validator is named directly — so both would
    # survive being deleted or left pointing at a version this is not. They are what every consumer
    # outside this project dispatches on: a wrong dialect is silently different semantics, and a
    # stale identity is the edit a copy made for the next version forgets.
    schema = _schema()

    assert schema["$schema"] == Draft202012Validator.META_SCHEMA["$id"]
    # The whole identity, not just its last segment. An identifier is the one thing a consumer
    # keys a cached copy by, so where it points is as much a part of it as what it is called —
    # and a suffix test would let the location move while the identity claimed not to have.
    assert schema["$id"] == (
        "https://raw.githubusercontent.com/GregoryGelfond/elenctic/main/"
        f"src/elenctic/schema/output-v{SCHEMA_VERSION}.schema.json"
    )


def test_the_corpus_these_tests_rest_on_reaches_every_register(document: dict[str, Any]) -> None:
    # The premise the rest of the file rests on, asserted as composition rather than as counts: if
    # the failing case ever stopped failing the counts would hold and the claims made about this
    # document would quietly become claims about something else.
    assert [case["verdict"] for case in document["cases"]] == ["pass", "fail"]
    assert [error["kind"] for error in document["errors"]] == ["contract"]
    assert {record["grade"] for record in document["hygiene"]} == {"warning", "silent"}


@pytest.mark.parametrize(
    ("strict", "budget", "deadline"),
    [
        (False, TIME_BUDGET, None),
        (True, TIME_BUDGET, None),
        (False, 2.5, 60.0),
        # The smallest durations a command line may ask for, and the direction the near-miss table
        # cannot see: a floor raised above a legal value refuses nothing any test here submits, so
        # the schema would come to reject the report of a run that was perfectly well made. What
        # such a run decides is not fixed — a budget this small interrupts every solve — and none
        # of that changes the shape, which is the whole of what is asserted.
        (False, 0.001, 0.001),
    ],
    ids=["default", "strict", "dialled", "barely-positive"],
)
def test_a_document_a_real_run_produced_is_one_the_schema_accepts(
    tmp_path: Path, strict: bool, budget: float, deadline: float | None
) -> None:
    # Every dial, not just the default position of each. Strictness is what grades an observation
    # `error`; a budget with a fractional part and a deadline that is a number rather than null are
    # the only things standing between the published types of those two fields and a narrowing that
    # no default-only run could notice.
    produced = _run(_corpus(tmp_path), strict=strict, budget=budget, deadline=deadline)

    # Validated after a round trip through the text, which is the form a consumer meets: a value
    # that survives the projection but not the rendering would otherwise never be looked at.
    _validator().validate(json.loads(dumps(produced)))


def test_a_run_where_nothing_went_wrong_is_one_the_schema_accepts(tmp_path: Path) -> None:
    # The modal document, and the one every other test here is blind to: each of the others carries
    # a non-empty `errors`, so a schema that came to require one would go on accepting all of them
    # while rejecting every report from a corpus that is simply fine.
    (tmp_path / "fine.lp").write_text(_PASSES, encoding="utf-8")
    document = _run(tmp_path)

    _validator().validate(document)
    assert document["errors"] == []
    assert document["hygiene"] == [], "the case declares its solver, and nothing is orphaned"
    assert document["cases"], "and there is something in the register that matters"


def test_a_run_that_found_nothing_to_run_is_still_a_document_the_schema_accepts(
    tmp_path: Path,
) -> None:
    # The corpus-scoped register, which no other document here reaches: no case produced a verdict,
    # so `cases` is empty and an error stands where they would have been. It is also the only shape
    # in which `source` is null rather than a file name, which is the whole of what defends that
    # field being published as nullable.
    document = _run(tmp_path / "nowhere")

    _validator().validate(document)
    assert document["cases"] == []
    (error,) = document["errors"]
    assert error["scope"] == "corpus", "the fault stopped the run, not one case"
    assert error["source"] is None, "a corpus-level fault belongs to no single file"


def test_the_document_is_json_that_a_strict_reader_accepts(document: dict[str, Any]) -> None:
    # This language reads back things that are not JSON, so a report can be well-formed here and
    # refused by every consumer it was written for. `parse_constant` fires on exactly those tokens.
    def refuse(literal: str) -> float:
        raise AssertionError(f"{literal} is not JSON — a consumer's parser will refuse the report")

    json.loads(dumps(document), parse_constant=refuse)


def test_a_number_with_no_json_form_is_refused_rather_than_written(
    document: dict[str, Any],
) -> None:
    # A budget can be given as infinite, and the obliging thing to do with it is to write
    # `Infinity`, which is not JSON. There being no document is the right outcome: a document a
    # consumer cannot parse is worse than an error saying why there is none.
    with pytest.raises(ValueError, match="not JSON compliant"):
        dumps(_edited(document, ("invocation", "budget"), float("inf")))


def test_the_same_corpus_yields_the_same_document_twice(tmp_path: Path) -> None:
    # The order promised at the top of the schema is promised of the run, not of the projection —
    # so pinning it over a fixed outcome cannot see order introduced by discovery or by the runner.
    corpus = _corpus(tmp_path)

    assert _run(corpus) == _run(corpus)


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


@pytest.mark.parametrize(("described", "in_document", "in_schema"), _OBJECTS, ids=_OBJECT_IDS)
def test_the_schema_requires_every_field_it_describes(
    described: str, in_document: tuple[str | int, ...], in_schema: tuple[str | int, ...]
) -> None:
    # A property described but not required does two things, and the second is the damage: it
    # documents a field nothing writes, and it takes that field's name out of the closed field
    # space, so a record carrying it validates. That is the shape of the likeliest real drift — the
    # schema edited first for a field the code has not got yet, and `required` forgotten.
    object_schema = _resolve(_schema(), in_schema)

    assert set(object_schema["properties"]) == set(object_schema["required"]), (
        f"{described} describes a field it does not require"
    )


@pytest.mark.parametrize(("described", "in_document", "in_schema"), _OBJECTS, ids=_OBJECT_IDS)
def test_every_field_a_consumer_meets_says_what_it_is(
    described: str, in_document: tuple[str | int, ...], in_schema: tuple[str | int, ...]
) -> None:
    # This file is the documentation, so a field that ships without prose is undocumented rather
    # than merely terse — and nothing else in the suite reads a description except the two that
    # enumerate open values, which leaves every other one deletable.
    schema = _schema()
    for name, field in _resolve(schema, in_schema)["properties"].items():
        assert _documented(field, schema), f"{described}'s {name} ships with nothing said about it"


def test_every_definition_the_schema_names_says_what_it_is() -> None:
    # A definition is reached by reference, and a reference to one may carry prose of its own — so
    # the definition's own description is read by nothing and would survive being deleted without
    # any field appearing undocumented. The one on `verdict` is where the three-valued reading is
    # explained, which is the sentence in this file it would cost a consumer most to lose.
    for name, definition in _schema()["$defs"].items():
        assert definition.get("description"), f"the {name} definition says nothing about itself"


@pytest.mark.parametrize(
    ("described", "path", "value"), _NEAR_MISSES, ids=[name for name, _, _ in _NEAR_MISSES]
)
def test_a_document_that_is_wrong_in_a_way_no_valid_document_shows_is_refused(
    document: dict[str, Any], described: str, path: tuple[str | int, ...], value: Any
) -> None:
    # The rejecting direction. Every constraint here mirrors something the package guarantees — a
    # case carries the reports its verdict came from, a contract line is 1-based, a count cannot go
    # negative — and each would be free to delete if the only question ever asked were whether a
    # valid document still validates.
    assert not _validator().is_valid(_edited(document, path, value)), (
        f"the schema accepted {described}"
    )


@pytest.mark.parametrize(
    ("path", "name"),
    [
        (("cases", 0, "verdict"), "PASS"),
        (("cases", 0, "checks", 0, "status"), "PASS"),
        (("cases", 0, "checks", 0, "conclusion"), "EXHAUSTED"),
        (("errors", 0, "scope"), "CASE"),
        (("hygiene", 0, "grade"), "WARNING"),
    ],
    ids=["verdict", "status", "conclusion", "scope", "grade"],
)
def test_a_closed_vocabulary_refuses_the_member_name_where_its_value_belongs(
    document: dict[str, Any], path: tuple[str | int, ...], name: str
) -> None:
    # Every closed vocabulary is written as its member's value, because that is what the ordinary
    # constructor reads back. The member's *name* is therefore the one wrong spelling a future edit
    # is most likely to reintroduce. This is also the only test that would notice the site being
    # unwired from the closed definition altogether — a `$ref` degraded to a bare string type.
    assert not _validator().is_valid(_edited(document, path, name)), (
        f"{name!r} was accepted where only its wire value belongs"
    )


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
    ("described", "path", "values"), _CLOSED, ids=[name for name, _, _ in _CLOSED]
)
def test_a_closed_vocabulary_is_exactly_what_the_package_can_emit(
    described: str, path: tuple[str | int, ...], values: frozenset[str]
) -> None:
    # Both directions are failures and neither is caught by validating a document: a member the
    # schema omits makes a valid document invalid the first time it occurs, and a member the schema
    # invents promises a value nothing will ever write.
    assert set(_resolve(_schema(), path)["enum"]) == values, (
        f"the {described} vocabulary has drifted"
    )


@pytest.mark.parametrize(("described", "path", "values"), _OPEN, ids=[name for name, _, _ in _OPEN])
def test_an_open_vocabulary_documents_every_value_this_version_can_emit(
    described: str, path: tuple[str | int, ...], values: frozenset[str]
) -> None:
    # The schema cannot constrain these, so its prose is the whole of what a reader is given. A
    # value added to the package and not to the prose is undocumented rather than merely unlisted.
    documented = _resolve(_schema(), path)["description"]
    for value in values:
        assert f"`{value}`" in documented, f"{described} can be {value!r} and does not say so"


def test_the_counts_are_the_registers_this_document_carries(document: dict[str, Any]) -> None:
    # The schema says the counts are there so a consumer need not walk the arrays, which is a
    # promise that walking them would agree. Asserted against a real document because that is where
    # the shapes are: this is the only run in the suite carrying an observation the run did not
    # report, and a count that quietly dropped it would agree with every synthetic register.
    counts = document["summary"]
    verdicts = [case["verdict"] for case in document["cases"]]

    assert counts["errors"] == len(document["errors"])
    assert counts["hygiene"] == len(document["hygiene"]), "a silent observation is still one"
    assert counts["passed"] == verdicts.count("pass")
    assert counts["failed"] == verdicts.count("fail")
    assert counts["undecided"] == verdicts.count("undecided")
    assert counts["total"] == len(verdicts) + sum(
        1 for error in document["errors"] if error["scope"] == "case"
    ), "every case discovered is accounted for, whether or not it reached a verdict"


def test_printing_the_schema_writes_the_packaged_file_and_nothing_else(
    capfdbinary: pytest.CaptureFixture[bytes],
) -> None:
    # Captured at the descriptor, which is what a shell redirect sees. Anything above it cannot
    # observe the encoding the bytes are written in, and the file is not ASCII.
    status = main(["--print-schema"])

    captured = capfdbinary.readouterr()
    assert status == ExitStatus.OK
    assert captured.out == schema_text().encode("utf-8")
    assert captured.err == b"", "nothing shares the stream the description is written to"


def test_printing_the_schema_asks_nothing_of_a_corpus(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # It is answered from the package alone, so it is answered before anything is looked for on
    # disk. A target that does not exist is a fault worth 2 on any other invocation, and someone
    # asking what the output looks like has no reason to have a corpus at all.
    status = main(["--print-schema", str(tmp_path / "no_such_corpus")])

    assert status == ExitStatus.OK
    assert capsys.readouterr().out == schema_text()


def test_a_copy_of_the_package_carrying_no_description_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Driven through the real lookup, at a name nothing ships, rather than by making the reader
    # raise: what is being checked is that a missing resource arrives as something the command line
    # recognises. The reader would otherwise reach the backstop, which prints a traceback and asks
    # for a bug report — sending someone whose installer dropped the data files to an issue tracker
    # that cannot help them.
    monkeypatch.setattr("elenctic.json_report.SCHEMA_VERSION", 999)

    status = main(["--print-schema"])

    captured = capsys.readouterr()
    assert status == ExitStatus.USER_FAULT, (
        "the environment is mis-shaped, which is a fault its owner can repair"
    )
    assert captured.out == "", "half a description is worse than none"
    assert "Traceback" not in captured.err, "an actionable fault is never delivered as a traceback"
    assert "elenctic/schema/" in captured.err, "and it says where the missing thing belongs"
    # Announced under the locus the record was filed with, like every other fault, rather than
    # under a word this frame chose for itself. The locus is the environment because that is what is
    # wrong: a copy of elenctic that has the code and not the data was assembled that way by
    # something downstream, and nothing about the corpus would change if it were fixed.
    assert captured.err.startswith("environment error: ")


# What each conclusion value must be glossed as. The pairing cannot be derived from the code — it is
# the meaning of the value rather than anything the value computes — so it is stated here, which is
# what makes exchanging two glosses in the published description a failing test rather than a
# document that confidently says the opposite of the truth.
_CONCLUSION_GLOSS = {
    "exhausted": "covered the space",
    "incomplete": "stopped short",
    "interrupted": "cut short from outside",
}


def test_the_description_of_each_conclusion_says_which_ending_it_names() -> None:
    # Every other test of this file's prose asks only whether there is any. A description is the
    # whole of what a consumer outside this project has to go on, so one that names the right values
    # and glosses them wrongly is worse than one that says nothing: it is confidently misleading,
    # and nothing about the document would look wrong.
    described = _schema()["$defs"]["check"]["properties"]["conclusion"]
    assert set(described["enum"]) == set(_CONCLUSION_GLOSS), (
        "a value gained or lost here needs its gloss written down beside it"
    )
    for value, gloss in _CONCLUSION_GLOSS.items():
        stated = re.search(rf"`{value}` means ([^;.]*)", described["description"])
        assert stated is not None, f"the description does not say what `{value}` means"
        assert gloss in stated.group(1), (
            f"`{value}` is glossed as {stated.group(1)!r}, which does not say {gloss!r}"
        )


def test_the_description_of_a_grade_states_the_footing_this_version_gives_each_kind() -> None:
    # Derived from the code that decides it, rather than restated: the default footing differs by
    # kind, and the whole point of the field is that a consumer is told what this run based its
    # status on. A description that swapped the two would contradict, in the published contract,
    # something the suite verifies in code — and nothing else here would notice.
    prose = _schema()["$defs"]["hygiene"]["properties"]["grade"]["description"]
    for kind in HygieneKind:
        phrase = kind.value.replace("_", " ")
        default = kind.grade_under(strict=False).value
        assert re.search(rf"{phrase} is (?:a )?`{default}`", prose), (
            f"the description does not say that an {phrase} defaults to `{default}`"
        )


def test_the_summary_description_does_not_claim_a_count_is_a_length_when_it_is_not(
    document: dict[str, Any],
) -> None:
    # Four of the six counts are not the length of anything, and the one that most invites the
    # assumption is `total`: reading it as the size of `cases` under-counts by exactly the cases
    # that could not be run, which is what it exists to include. The fact is measured here first, so
    # the sentence is tied to something rather than merely to itself.
    prose = _schema()["$defs"]["summary"]["description"]
    for register in ("errors", "hygiene"):
        assert document["summary"][register] == len(document[register])
    assert document["summary"]["total"] != len(document["cases"]), (
        "the corpus behind this fixture must hold a case that produced no verdict, or there is "
        "nothing here for the description to get wrong"
    )
    assert "Only `errors` and `hygiene` are the lengths" in prose
