import dataclasses
import enum
import importlib
import json
import pkgutil
import re
import typing

import pytest
from write_output_schema import TARGET, render

import elenctic
from elenctic.contract import Census, Entails
from elenctic.determination import AnswerSet, Incumbent, Truncation, WorldView
from elenctic.json_view import SCHEMA, encode, kind_of, schema_document, to_json
from elenctic.report import Entry, Exit, Run
from elenctic.spans import Position
from elenctic.verdicts import Ended, Report
from runs import FAILING, PROGRAM_WITH_ESCAPE_CODES, entry


def test_json_is_derived_from_the_result_types() -> None:
    document = json.loads(to_json(Run((entry(FAILING, "b.lp"),))))
    assert document["schema"] == SCHEMA
    assert document["exit_code"] == Exit.CLAIM_UNMET
    (only,) = document["run"]["entries"]
    report = only["result"]
    assert report["kind"] == "report"
    claim = report["findings"][1]["claim"]
    assert claim["reading"] == {
        "kind": "entails",
        "mode": "cautious",
        "literals": ["q"],
        "over": "all",
    }
    assert claim["span"]["start"] == {"kind": "position", "line": 3, "column": 3}
    assert report["findings"][1]["verdict"] == "fail"


def test_a_type_is_not_a_result_and_is_not_encoded() -> None:
    with pytest.raises(TypeError, match="cannot encode type"):
        encode(Entry)
    with pytest.raises(TypeError, match="cannot encode object"):
        encode(object())


def test_json_keeps_the_program_text_and_its_encoder_escapes_control_characters() -> None:
    written = to_json(Run((entry(PROGRAM_WITH_ESCAPE_CODES, "a.lp"),)))
    detail = json.loads(written)["run"]["entries"][0]["result"]["findings"][1]["detail"]
    assert "\x1b[2J\x1b[31m" in detail
    assert "\x1b" not in written
    assert "\\u001b[2J" in written


def _string_enums() -> list[type[enum.StrEnum]]:
    modules = [
        importlib.import_module(f"elenctic.{m.name}")
        for m in pkgutil.iter_modules(elenctic.__path__)
    ]
    return [
        value
        for module in modules
        for value in vars(module).values()
        if isinstance(value, type)
        and issubclass(value, enum.StrEnum)
        and value.__module__ == module.__name__
    ]


def test_every_string_enum_has_snake_case_values_named_for_its_members() -> None:
    enums = _string_enums()
    assert Truncation in enums
    for each in enums:
        for member in each:
            assert re.fullmatch(r"[a-z]+(_[a-z]+)*", member.value), member
            assert member.value == member.name.lower(), member


def test_a_truncation_is_encoded_in_snake_case() -> None:
    assert encode(Truncation.MAX_ANSWER_SETS) == "max_answer_sets"
    assert encode(Truncation.MAX_SECONDS) == "max_seconds"


def _result_types(found: set[type], hint: object) -> set[type]:
    """Collect the dataclasses a hint can lead to, following every field."""
    if isinstance(hint, typing.TypeAliasType):
        return _result_types(found, hint.__value__)
    for part in typing.get_args(hint):
        _result_types(found, part)
    if isinstance(hint, type) and dataclasses.is_dataclass(hint) and hint not in found:
        found.add(hint)
        for field in typing.get_type_hints(hint).values():
            _result_types(found, field)
    return found


def test_every_kind_a_run_can_carry_is_snake_case_and_names_one_type() -> None:
    types = _result_types(set(), Run)
    assert {Run, Report, Entails, Census, Position} <= types
    kinds = [kind_of(each) for each in types]
    assert all(re.fullmatch(r"[a-z]+(_[a-z]+)*", kind) for kind in kinds)
    assert len(set(kinds)) == len(types)


def test_a_kind_is_the_type_name_in_snake_case() -> None:
    assert [kind_of(each) for each in (Census, AnswerSet, WorldView)] == [
        "census",
        "answer_set",
        "world_view",
    ]
    answer_set = AnswerSet(frozenset(), frozenset(), assignment=frozenset(), cost=())
    assert encode(Incumbent(answer_set)) == {
        "kind": "incumbent",
        "answer_set": {
            "kind": "answer_set",
            "atoms": [],
            "shown": [],
            "assignment": [],
            "cost": [],
        },
    }


def test_a_search_cut_short_is_encoded_as_the_limit_that_ended_it() -> None:
    assert encode(Ended(Truncation.MAX_SECONDS)) == {
        "kind": "ended",
        "cut": "max_seconds",
        "optimum_unproven": False,
    }


def test_the_published_schema_is_what_the_types_describe() -> None:
    assert TARGET.read_text() == render()


def test_the_schema_document_names_schema_one_and_the_run_kinds() -> None:
    document = schema_document()
    properties = document["properties"]
    defs = document["$defs"]
    assert isinstance(properties, dict)
    assert isinstance(defs, dict)
    assert properties["schema"] == {"const": SCHEMA}
    assert "run" in defs
    assert "literal" not in defs
    assert "pattern" not in defs
    assert render().endswith("\n")
