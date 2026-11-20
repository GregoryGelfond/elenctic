import dataclasses
import enum
import importlib
import json
import pkgutil
import re
import typing
from pathlib import Path

import pytest
from clingo import Number
from write_output_schema import TARGET, render

import elenctic
from elenctic.about import package
from elenctic.check import check
from elenctic.contract import Census, Entails
from elenctic.determination import AnswerSet, Incumbent, Truncation, WorldView
from elenctic.inquiry import AskExit, WhyExit, ask, why
from elenctic.json_view import SCHEMA, encode, inquiry_json, kind_of, schema_document, to_json
from elenctic.literals import Literal
from elenctic.patterns import Pattern
from elenctic.program import Program
from elenctic.query import All
from elenctic.report import Entry, Exit, Run
from elenctic.session import evidenced
from elenctic.spans import Position
from elenctic.terms import Variable
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


def test_the_schema_is_published_under_the_tag_of_the_packages_version() -> None:
    assert f"/elenctic/v{package().version}/docs/" in str(schema_document()["$id"])


def _explained(name: str) -> Run:
    program = Program.read(Path(__file__).parent.parent / "docs" / "examples" / name)
    report = check(program)
    assert isinstance(report, Report)
    found = evidenced(report, program, max_depth=3)
    assert isinstance(found, Report)
    return Run((Entry(program.source, found, program.text),))


def _objects(value: object) -> list[dict[str, object]]:
    """Every kind-tagged object in a decoded document, depth first."""
    found: list[dict[str, object]] = []
    pending = [value]
    while pending:
        each = pending.pop()
        if isinstance(each, dict):
            found.append(each)
            pending.extend(each.values())
        elif isinstance(each, list):
            pending.extend(each)
    return [each for each in found if "kind" in each and isinstance(each["kind"], str)]


@pytest.mark.parametrize("name", ["absent.lp", "chain.lp", "laptop.lp", "team.lp"])
def test_each_object_of_an_explained_run_has_the_keys_its_schema_names(name: str) -> None:
    defs = schema_document()["$defs"]
    assert isinstance(defs, dict)
    document = json.loads(to_json(_explained(name)))
    for each in _objects(document["run"]):
        schema = defs[str(each["kind"])]
        assert isinstance(schema, dict)
        properties, required = schema["properties"], schema["required"]
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        assert set(each) <= set(properties), each["kind"]
        assert set(required) <= set(each), each["kind"]


def test_a_finding_without_evidence_has_no_evidence_key() -> None:
    document = json.loads(to_json(Run((entry(FAILING, "b.lp"),))))
    (only,) = document["run"]["entries"]
    assert all("evidence" not in finding for finding in only["result"]["findings"])


def test_evidence_writes_a_substitution_as_a_string_and_handles_as_text() -> None:
    document = json.loads(to_json(_explained("absent.lp")))
    (only,) = document["run"]["entries"]
    evidence = only["result"]["findings"][1]["evidence"]
    assert evidence["kind"] == "explanation"
    assert evidence["roots"] == ["1/not access(ann,db)"]
    assert (evidence["minimality"], evidence["max_depth"], evidence["complete"]) == (
        "none",
        3,
        True,
    )
    blocked = evidence["nodes"][1]["reason"]
    assert blocked["kind"] == "blocked"
    assert blocked["substitution"] == "{R=db, U=ann, X=admin}"
    assert blocked["literal"] == "not suspended(ann)"


def test_an_outranked_result_is_one_kind_with_its_explanation_as_a_field() -> None:
    document = json.loads(to_json(_explained("laptop.lp")))
    (only,) = document["run"]["entries"]
    evidence = only["result"]["findings"][1]["evidence"]
    assert evidence["kind"] == "outranked"
    assert (evidence["optimum"], evidence["assuming"], evidence["priorities"]) == (
        [0, 230],
        [0, 380],
        [2, 1],
    )
    assert evidence["explanation"]["kind"] == "explanation"
    assert evidence["assuming_only"][0]["terms"] == ["ram"]


def test_the_schema_adds_to_schema_one_and_makes_evidence_optional() -> None:
    defs = schema_document()["$defs"]
    assert isinstance(defs, dict)
    finding = defs["finding"]
    assert isinstance(finding, dict)
    assert finding["required"] == ["kind", "claim", "verdict", "detail"]
    assert {"explanation", "outranked", "node", "counterexample", "blocked"} <= set(defs)
    assert "substitution" not in defs


def test_a_set_of_literals_is_listed_in_the_order_the_text_lists_it() -> None:
    literals = frozenset(Literal.parse(f"p({n})") for n in (10, 2, 1))
    assert encode(literals) == ["p(1)", "p(2)", "p(10)"]
    encoded = encode(AnswerSet(literals, literals))
    assert isinstance(encoded, dict)
    assert encoded["shown"] == ["p(1)", "p(2)", "p(10)"]


def test_bindings_are_listed_in_the_order_the_text_writes_them() -> None:
    rows = frozenset({(Number(10),), (Number(2),)})
    assert encode(rows) == [["2"], ["10"]]


def _keys_follow_schema(document: object) -> None:
    defs = schema_document()["$defs"]
    assert isinstance(defs, dict)
    for each in _objects(document):
        schema = defs[str(each["kind"])]
        assert isinstance(schema, dict)
        properties, required = schema["properties"], schema["required"]
        assert isinstance(properties, dict)
        assert isinstance(required, list)
        assert set(each) <= set(properties), each["kind"]
        assert set(required) <= set(each), each["kind"]


def test_why_and_ask_documents_add_to_schema_one_under_their_names() -> None:
    document = schema_document()
    properties, alternatives = document["properties"], document["oneOf"]
    assert isinstance(properties, dict)
    assert {"run", "why", "ask"} <= set(properties)
    assert document["required"] == ["schema", "exit_code"]
    assert alternatives == [{"required": ["run"]}, {"required": ["why"]}, {"required": ["ask"]}]
    defs = document["$defs"]
    assert isinstance(defs, dict)
    assert {"answered", "taken", "bindings", "explanation", "internal", "fault"} <= set(defs)


def test_an_answer_is_written_with_the_answer_sets_that_give_it() -> None:
    program = Program("{ a; b }.\n-c.\n", "ab.lp")
    answered = ask(program, All((Literal("a"),)))
    document = json.loads(inquiry_json("ask", answered, AskExit.of(answered)))
    assert document["exit_code"] == 0
    assert document["ask"]["query"] == {"kind": "all", "parts": ["a"]}
    assert document["ask"]["taken"][1]["answer_set"]["shown"] == ["a", "-c"]
    _keys_follow_schema(document)
    pattern = ask(Program("p(1). { p(2) }.", "p.lp"), Pattern("p", (Variable("X"),)))
    bound = json.loads(inquiry_json("ask", pattern, AskExit.of(pattern)))
    assert bound["ask"]["answer"] == {
        "kind": "bindings",
        "yes": [["1"]],
        "no": [],
        "unknown": [["2"]],
    }
    _keys_follow_schema(bound)
    explained = why(program, Literal("a"), index=3)
    _keys_follow_schema(json.loads(inquiry_json("why", explained, WhyExit.of(explained))))
