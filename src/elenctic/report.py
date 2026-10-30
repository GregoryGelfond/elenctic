"""Present results: JSON derived from the result types, and a line-per-claim text."""

import json
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import TypeIs

from elenctic.literals import Literal, Symbol
from elenctic.patterns import Pattern
from elenctic.program import Fault
from elenctic.verdicts import Finding, Report, Verdict

SCHEMA = 1

type Json = bool | int | str | list[Json] | dict[str, Json] | None


@dataclass(frozen=True, slots=True)
class Entry:
    """What checking one source came to."""

    source: str
    result: Report | Fault


@dataclass(frozen=True, slots=True)
class Run:
    entries: tuple[Entry, ...]

    @property
    def exit_code(self) -> int:
        """Two if any source could not be checked, else one unless every claim passed."""
        results = [entry.result for entry in self.entries]
        if any(isinstance(result, Fault) for result in results):
            return 2
        return int(any(r.verdict is not Verdict.PASS for r in results if isinstance(r, Report)))


def _is_ordered(value: object) -> TypeIs[tuple[object, ...] | list[object]]:
    return isinstance(value, tuple | list)


def _is_unordered(value: object) -> TypeIs[frozenset[object] | set[object]]:
    return isinstance(value, frozenset | set)


def _record(value: object) -> Json:
    """Encode a dataclass as an object tagged with its type's name; nothing else is encodable."""
    if not is_dataclass(value) or isinstance(value, type):
        message = f"cannot encode {type(value).__name__}"
        raise TypeError(message)
    return {"kind": type(value).__name__} | {
        field.name: encode(getattr(value, field.name)) for field in fields(value)
    }


def encode(value: object) -> Json:
    """Encode a result value; a dataclass becomes an object tagged with its type's name."""
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


def _line(finding: Finding) -> str:
    start = finding.claim.span.start
    return f"  [{finding.verdict.name}] {finding.claim_text} (line {start.line}): {finding.detail}"


def _fault(fault: Fault) -> list[str]:
    return [f"{d.span}: {d.severity}: {d.message}" for d in fault.diagnostics] or [str(fault.locus)]


def _entry(entry: Entry, *, verbose: bool) -> list[str]:
    match entry.result:
        case Fault() as fault:
            return _fault(fault)
        case Report(source, findings) as report if verbose or report.verdict is not Verdict.PASS:
            shown = [f for f in findings if verbose or f.verdict is not Verdict.PASS]
            return [f"{source} — {report.verdict.name}", *map(_line, shown), ""]
        case _:
            return []


def _summary(run: Run) -> str:
    reports = [e.result for e in run.entries if isinstance(e.result, Report)]
    counts = {v: sum(r.verdict is v for r in reports) for v in Verdict}
    faults = len(run.entries) - len(reports)
    tail = [f"{counts[v]} {v.value}" for v in (Verdict.FAIL, Verdict.UNDECIDED) if counts[v]]
    tail += [f"{faults} error"] if faults else []
    return f"{counts[Verdict.PASS]}/{len(run.entries)} passed" + "".join(f", {t}" for t in tail)


def to_text(run: Run, *, verbose: bool = False) -> str:
    """Write a run as text: each source that did not pass, with its claims that did not."""
    lines = [line for entry in run.entries for line in _entry(entry, verbose=verbose)]
    return "\n".join([*lines, _summary(run)])
