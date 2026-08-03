"""The machine-readable report: one run's outcome as a single JSON document.

The sibling of the human render, and pure in the same way — it builds a document and returns it,
touching no file and no stream. What it produces is a published contract, so it serializes the
structured records rather than the prose the human renderer composes: a consumer reading a message
for its meaning is reading something free to change, while the fields beside it are not.

Everything the corpus controls — a file name, an atom, a solver's own diagnostic — passes through
the shared sanitizer before it reaches the document. That is the same guarantee the terminal
renderer needs and for a related reason: text a reader's tooling would act on rather than display
can rewrite the report it appears in. It also settles a narrower question the terminal never faces.
A file name whose bytes are not valid UTF-8 reaches Python as a lone surrogate, which has no
encoding at all — so a document carrying one raw would fail at the moment of writing rather than at
the moment of reading, and the run would have nothing to show for itself. The same seam neutralizes
the two separator characters that end a line for some readers of JSON and would split a document
required to be exactly one.
"""

import json
from importlib.resources import files
from pathlib import Path
from typing import Final

from elenctic.checks import CheckReport
from elenctic.display import legible
from elenctic.outcome import (
    CaseOutcome,
    ErrorRecord,
    HygieneRecord,
    Invocation,
    RunOutcome,
    summary,
)

__all__ = ["SCHEMA_VERSION", "as_json", "dumps", "schema_text"]

SCHEMA_VERSION: Final = 1
"""The version of the document's shape.

It changes when a field is added or removed, or when one of the closed enumerations gains a member
— never when a new value appears in one of the open-valued string fields, which is what lets a
locus or a tag be added without invalidating a consumer written against this version.
"""


def as_json(outcome: RunOutcome, invocation: Invocation) -> dict[str, object]:
    """One run's outcome as the document, ready to be rendered.

    Order is the run's own throughout — nothing is sorted — so the same input yields the same
    document, and a case's position in its array is its identity within it.

    Every closed vocabulary is written as its member's value rather than its member's name, because
    the value is what the ordinary constructor reads back: a consumer holding this document and the
    package can write ``Verdict(case["verdict"])`` and have it work.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "invocation": {
            "target": _text(invocation.target),
            "strict": invocation.strict,
            "budget": invocation.budget,
            "deadline": invocation.deadline,
        },
        "summary": summary(outcome),
        "cases": [_case(case) for case in outcome.cases],
        "errors": [_error(record) for record in outcome.errors],
        "hygiene": [_hygiene(record) for record in outcome.hygiene],
    }


def dumps(document: dict[str, object]) -> str:
    """Render a document as the exact text to write: one object, two-space indented, one trailing
    newline.

    ``ensure_ascii`` is off because the sanitizer has already removed everything that would need
    escaping for safety, so what remains is legible as itself — the atoms of an answer set read as
    the program wrote them.
    """
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def schema_text() -> str:
    """The packaged description of the document's shape, exactly as it ships.

    Text rather than a parsed object: the caller that is not a test writes it to standard output,
    and someone redirecting that into a file should get the file. Parsing and re-rendering it would
    hand them something that says the same thing in a different shape, and the whitespace of a
    published document is part of what people diff.

    The version is in the resource's name rather than beside it, because the shape of a document and
    the description of that shape are one fact. A bump that renamed the constant and not the file
    would otherwise go on printing the description of a document the package no longer produces;
    this way it finds nothing, and a copy of the package missing the file at all is reported the
    same way — as elenctic's own fault, which is what a packaging fault is.
    """
    resource = files("elenctic") / "schema" / f"output-v{SCHEMA_VERSION}.schema.json"
    return resource.read_text(encoding="utf-8")


def _case(outcome: CaseOutcome) -> dict[str, object]:
    return {
        "source": _text(outcome.case.path),
        "solver": _text(outcome.case.solver),
        "verdict": outcome.verdict.value,
        "checks": [_check(report) for report in outcome.reports],
    }


def _check(report: CheckReport) -> dict[str, object]:
    return {
        "tag": _text(report.label),
        "subject": _text(report.subject),
        "status": report.verdict.value,
        "message": _text(report.message),
        "line": report.line,
        "conclusion": report.conclusion.value,
    }


def _error(record: ErrorRecord) -> dict[str, object]:
    return {
        "kind": record.kind.value,
        # Stated rather than left to be derived. This is the closed, two-valued question the exit
        # status turns on, while the locus beside it is the growable tier — so a consumer meeting a
        # locus added in a later version could otherwise answer it only by keeping a table of loci
        # in step with a version it does not have.
        "is_elenctic_bug": record.kind.is_elenctic_bug,
        "scope": record.scope.value,
        "source": None if record.source is None else _text(record.source),
        "message": _text(record.message),
    }


def _hygiene(record: HygieneRecord) -> dict[str, object]:
    return {
        "kind": record.kind.value,
        "severity": record.severity.value,
        "source": _text(record.source),
        "message": _text(record.message),
    }


def _text(value: str | Path) -> str:
    """Anything the corpus had a hand in, made safe to carry.

    One seam for every such string rather than a judgment per field: which of these a corpus can
    reach is a question the answer to which changes, and a field added later inherits the guarantee
    only if there is one place to add it to.
    """
    return legible(str(value))
