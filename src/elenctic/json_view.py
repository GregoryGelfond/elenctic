"""The JSON view of a run: derived from the result types, never styled."""

import json
import re
import typing
from dataclasses import fields, is_dataclass
from enum import Enum, IntEnum
from types import UnionType
from typing import Final, TypeIs, cast

from elenctic.about import package
from elenctic.inquiry import Ask, AskExit, Why, WhyExit
from elenctic.legend import listed
from elenctic.literals import Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.report import Entry, Exit, Internal, Run
from elenctic.substitution import Substitution
from elenctic.verdicts import Finding, Report, Verdict

SCHEMA = 1

type Json = bool | int | str | list[Json] | dict[str, Json] | None

_AS_STRING: Final = (Symbol, Literal, Pattern, Substitution)
"""Types `encode` writes as a string rather than as a kind-tagged object."""

_SEQUENCE: Final = (tuple, list, set, frozenset)

_SCHEMA_ID: Final = (
    "https://raw.githubusercontent.com/GregoryGelfond/elenctic/v{version}/docs/reference/"
    "output-v1.schema.json"
)
"""Where the schema of a release is published: under its tag, from the package's version."""


def _is_ordered(value: object) -> TypeIs[tuple[object, ...] | list[object]]:
    return isinstance(value, tuple | list)


def _is_unordered(value: object) -> TypeIs[frozenset[object] | set[object]]:
    return isinstance(value, frozenset | set)


def kind_of(type_: type) -> str:
    """Name a type for the `kind` of its objects: its name in snake case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", type_.__name__).lower()


def _record(value: object) -> Json:
    """Encode a dataclass as an object tagged with its type's kind; nothing else is encodable."""
    if not is_dataclass(value) or isinstance(value, type):
        message = f"cannot encode {type(value).__name__}"
        raise TypeError(message)
    encoded = {
        field.name: encode(getattr(value, field.name))
        for field in fields(value)
        if not (isinstance(value, Entry) and field.name == "text")
        and not _unasked(value, field.name)
    }
    record: dict[str, Json] = {"kind": kind_of(type(value)), **encoded}
    if isinstance(value, Report):
        record["verdict"] = encode(value.verdict)
    return record


def _unasked(value: object, name: str) -> bool:
    """Say whether a field is left out: evidence none was asked for or found, or no libraries."""
    match value:
        case Finding():
            return name == "evidence" and value.evidence is None
        case Entry():
            return name == "libraries" and not value.libraries
        case _:
            return False


def _listed(items: frozenset[object] | set[object]) -> Json:
    """Encode a set in the legend's order, or, if its elements have none, by their encoding."""
    ordered = listed(items)
    if ordered is not None:
        return [encode(item) for item in ordered]
    return sorted((encode(item) for item in items), key=json.dumps)


def encode(value: object) -> Json:
    """Encode a result value; a dataclass becomes an object tagged with its type's kind."""
    match value:
        case Enum():
            return encode(value.value)
        case None | bool() | int() | str():
            return value
        case Symbol() | Literal() | Pattern() | Substitution():
            return str(value)
        case _ if _is_ordered(value):
            return [encode(item) for item in value]
        case _ if _is_unordered(value):
            return _listed(value)
        case _:
            return _record(value)


def to_json(run: Run) -> str:
    """Write a run as one JSON document."""
    return (
        json.dumps({"schema": SCHEMA, "run": encode(run), "exit_code": run.exit_code}, indent=2)
        + "\n"
    )


def inquiry_json(command: str, result: object, exit_code: int) -> str:
    """Write what a question found as one JSON document, under the command's name."""
    return (
        json.dumps({"schema": SCHEMA, command: encode(result), "exit_code": exit_code}, indent=2)
        + "\n"
    )


def _unwrap(hint: object) -> object:
    return hint.__value__ if isinstance(hint, typing.TypeAliasType) else hint


def _parts(hint: object) -> tuple[object, ...]:
    """Name the alternatives of a union, those of any union among them too, or the hint alone."""
    hint = _unwrap(hint)
    if typing.get_origin(hint) is UnionType:
        return tuple(part for arg in typing.get_args(hint) for part in _parts(arg))
    return (hint,)


def _object_types(found: set[type], hint: object) -> set[type]:
    """Collect the dataclasses a run encodes as kind-tagged objects."""
    for part in _parts(hint):
        _collect(found, _unwrap(part))
    return found


def _collect(found: set[type], part: object) -> None:
    """Collect one non-union hint: the arguments of a generic, or a dataclass and its fields."""
    if typing.get_origin(part) is not None:
        for arg in typing.get_args(part):
            _object_types(found, arg)
    elif isinstance(part, type) and is_dataclass(part) and part not in {*_AS_STRING, *found}:
        found.add(part)
        for field in typing.get_type_hints(part).values():
            _object_types(found, field)


def _schema_for(hint: object) -> Json:
    """Describe what `encode` writes for a value of `hint`."""
    unique: list[Json] = []
    for part in _parts(hint):
        each = _schema_alternative(part)
        if each not in unique:
            unique.append(each)
    return unique[0] if len(unique) == 1 else {"oneOf": unique}


def _sequence_schema(hint: object) -> Json:
    """Describe a list or set: an array whose items follow the element hint."""
    return {"type": "array", "items": _schema_for(typing.get_args(hint)[0])}


def _enum_schema(type_: type[Enum]) -> Json:
    """Describe an enum as `encode` writes it: its values."""
    if issubclass(type_, IntEnum):
        return {"type": "integer", "enum": [member.value for member in type_]}
    return {"type": "string", "enum": [member.value for member in type_]}


def _schema_alternative(hint: object) -> Json:
    """Describe one non-union hint as `encode` writes it."""
    hint = _unwrap(hint)
    origin = typing.get_origin(hint)
    if origin in _SEQUENCE:
        return _sequence_schema(hint)
    primitives: dict[type, str] = {str: "string", bool: "boolean", int: "integer"}
    if hint is type(None):
        return {"type": "null"}
    named = cast("type[object]", hint)
    if named in _AS_STRING or named in primitives:
        return {"type": "string" if named in _AS_STRING else primitives[named]}
    if issubclass(named, Enum):
        return _enum_schema(named)
    if is_dataclass(named):
        return {"$ref": f"#/$defs/{kind_of(named)}"}
    message = f"cannot describe {hint!r}"
    raise TypeError(message)


_OPTIONAL_FIELDS: Final = {
    "diagnostic": frozenset({"label", "children"}),
    "entry": frozenset({"text", "libraries"}),
    "finding": frozenset({"evidence"}),
    "report": frozenset({"lints"}),
    "run": frozenset({"notes"}),
}


def _object_schema(type_: type) -> Json:
    """Describe a kind-tagged object: `kind` and each dataclass field, nothing else."""
    hints = typing.get_type_hints(type_)
    kind = kind_of(type_)
    optional = _OPTIONAL_FIELDS.get(kind, frozenset())
    properties: dict[str, Json] = {"kind": {"const": kind}}
    required: list[Json] = ["kind"]
    for field in fields(type_):
        if kind == "entry" and field.name == "text":
            continue  # not encoded; kept only for snippets
        properties[field.name] = _schema_for(hints[field.name])
        if field.name not in optional:
            required.append(field.name)
    if kind == "report":
        properties["verdict"] = {"type": "string", "enum": [member.value for member in Verdict]}
        required.append("verdict")
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def _codes() -> list[Json]:
    """List the statuses a command can exit with: those of a run and of each question."""
    codes: list[Json] = []
    for each in (Exit, WhyExit, AskExit):
        codes += [member.value for member in each if member.value not in codes]
    return codes


_QUESTIONS: Final = {"why": Why | Internal, "ask": Ask | Internal}
"""What each question's document holds, under the question's name."""


def schema_document() -> dict[str, Json]:
    """Build the JSON Schema of a `--json` document from the result types `encode` walks.

    A document holds a test run, or what `why` or `ask` found, under its command's name.
    """
    found = _object_types(set(), Run)
    for hint in _QUESTIONS.values():
        _object_types(found, hint)
    types = sorted(found, key=kind_of)
    defs = {kind_of(each): _object_schema(each) for each in types}
    diagnostic = cast("dict[str, Json]", defs["diagnostic"])
    properties = cast("dict[str, Json]", diagnostic["properties"])
    properties["code"] = {
        "oneOf": [{"type": "string"}, {"type": "null"}],
        "description": "Reserved; unused in schema 1.",
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": _SCHEMA_ID.format(version=package().version),
        "title": "elenctic output schema 1",
        "type": "object",
        "required": ["schema", "exit_code"],
        "properties": {
            "schema": {"const": SCHEMA},
            "run": {"$ref": "#/$defs/run"},
            **{name: _schema_for(hint) for name, hint in _QUESTIONS.items()},
            "exit_code": {
                "type": "integer",
                "enum": _codes(),
                "description": "The status the command exits with: the Exit of a test run, or "
                "the WhyExit or AskExit of a question (0, 1, 2, or 3).",
            },
        },
        "oneOf": [{"required": [name]} for name in ("run", *_QUESTIONS)],
        "additionalProperties": False,
        "$defs": defs,
    }
