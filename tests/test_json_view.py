import enum
import importlib
import json
import pkgutil
import re

import pytest

import elenctic
from elenctic.determination import Truncation
from elenctic.json_view import SCHEMA, encode, to_json
from elenctic.report import Entry, Exit, Run
from runs import FAILING, PROGRAM_WITH_ESCAPE_CODES, entry


def test_json_is_derived_from_the_result_types() -> None:
    document = json.loads(to_json(Run((entry(FAILING, "b.lp"),))))
    assert document["schema"] == SCHEMA
    assert document["exit_code"] == Exit.CLAIM_UNMET
    (only,) = document["run"]["entries"]
    report = only["result"]
    assert report["kind"] == "Report"
    claim = report["findings"][1]["claim"]
    assert claim["reading"] == {
        "kind": "Entails",
        "mode": "cautious",
        "literals": ["q"],
        "over": "all",
    }
    assert claim["span"]["start"] == {"kind": "Position", "line": 3, "column": 3}
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
