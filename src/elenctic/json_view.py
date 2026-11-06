"""The JSON view of a run: derived from the result types, never styled."""

import json
import re
import typing
from dataclasses import fields, is_dataclass
from enum import Enum, IntEnum
from types import UnionType
from typing import Final, TypeIs, cast

from elenctic.literals import Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.report import Exit, Run

SCHEMA = 1

type Json = bool | int | str | list[Json] | dict[str, Json] | None

_AS_STRING: Final = (Symbol, Literal, Pattern)
"""Types `encode` writes as a string rather than as a kind-tagged object."""

_SEQUENCE: Final = (tuple, list, set, frozenset)


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
    return {"kind": kind_of(type(value))} | {
        field.name: encode(getattr(value, field.name)) for field in fields(value)
    }


def encode(value: object) -> Json:
    """Encode a result value; a dataclass becomes an object tagged with its type's kind."""
    match value:
        case Enum():
            return encode(value.value)
        case None | bool() | int() | str():
            return value
        case Symbol() | Literal() | Pattern():
            return str(value)
        case _ if _is_ordered(value):
            return [encode(item) for item in value]
        case _ if _is_unordered(value):
            return sorted((encode(item) for item in value), key=json.dumps)
        case _:
            return _record(value)


def to_json(run: Run) -> str:
    """Write a run as one JSON document."""
    return json.dumps({"schema": SCHEMA, "run": encode(run), "exit_code": run.exit_code}, indent=2)


def _unwrap(hint: object) -> object:
    return hint.__value__ if isinstance(hint, typing.TypeAliasType) else hint


def _parts(hint: object) -> tuple[object, ...]:
    """Name the alternatives of a union, or the hint alone."""
    hint = _unwrap(hint)
    origin = typing.get_origin(hint)
    if origin is UnionType:
        return typing.get_args(hint)
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
    named = cast("type[object]", hint)
    if named in _AS_STRING or named in primitives:
        return {"type": "string" if named in _AS_STRING else primitives[named]}
    if issubclass(named, Enum):
        return _enum_schema(named)
    if is_dataclass(named):
        return {"$ref": f"#/$defs/{kind_of(named)}"}
    message = f"cannot describe {hint!r}"
    raise TypeError(message)


def _object_schema(type_: type) -> Json:
    """Describe a kind-tagged object: `kind` and each dataclass field, nothing else."""
    hints = typing.get_type_hints(type_)
    properties: dict[str, Json] = {"kind": {"const": kind_of(type_)}}
    required: list[Json] = ["kind"]
    for field in fields(type_):
        properties[field.name] = _schema_for(hints[field.name])
        required.append(field.name)
    return {
        "type": "object",
        "required": required,
        "properties": properties,
        "additionalProperties": False,
    }


def schema_document() -> dict[str, Json]:
    """Build the JSON Schema of a `--json` document from the result types `encode` walks."""
    types = sorted(_object_types(set(), Run), key=kind_of)
    defs = {kind_of(each): _object_schema(each) for each in types}
    diagnostic = cast("dict[str, Json]", defs["diagnostic"])
    properties = cast("dict[str, Json]", diagnostic["properties"])
    properties["code"] = {
        "oneOf": [{"type": "string"}, {"type": "null"}],
        "description": "Reserved; unused in schema 1.",
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://github.com/GregoryGelfond/elenctic/docs/reference/output-v1.schema.json",
        "title": "elenctic output schema 1",
        "type": "object",
        "required": ["schema", "run", "exit_code"],
        "properties": {
            "schema": {"const": SCHEMA},
            "run": {"$ref": "#/$defs/run"},
            "exit_code": {
                "type": "integer",
                "enum": [member.value for member in Exit],
                "description": "The Exit of the test run (0, 1, 2, or 3).",
            },
        },
        "additionalProperties": False,
        "$defs": defs,
    }
