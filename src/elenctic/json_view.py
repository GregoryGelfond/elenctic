"""The JSON view of a run: derived from the result types, never styled."""

import json
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import TypeIs

from elenctic.literals import Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.report import Run

SCHEMA = 1

type Json = bool | int | str | list[Json] | dict[str, Json] | None


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
