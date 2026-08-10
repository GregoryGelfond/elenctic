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

SCHEMA_VERSION: Final = 2
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

    ``allow_nan`` is off because it is on by default, and what it allows is not JSON: a non-finite
    float is written as a bare ``Infinity`` or ``NaN``, which this language reads back and most
    others refuse outright — so a document carrying one is one the consumer this exists for cannot
    parse at all. The two numbers a caller supplies are the budget and the deadline, and a caller
    can supply either as infinite. Refusing here makes the rule that there is a document or there is
    an error, never a document that is not JSON; telling the caller so in terms of what they typed
    is the command line's part, since by this point the value has lost the name it arrived under.
    """
    return json.dumps(document, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def schema_text() -> str:
    """The packaged description of the document's shape, exactly as it ships — or the reason there
    is no description to hand back.

    Text rather than a parsed object: the caller that is not a test writes it to standard output,
    and someone redirecting that into a file should get the file. Parsing and re-rendering it would
    hand them something that says the same thing in a different shape, and the whitespace of a
    published document is part of what people diff.

    **Parsed to check, never to render.** What is returned is the file, byte for byte; the parse
    establishes only that the file *is* a description before anyone is handed one. A packaging or
    vendoring step can drop this file, re-encode it, or leave it half written, and the three are one
    accident with one remedy — but only the first two announce themselves, by raising on the way out
    of the read. A file cut short is read back perfectly happily as a string that describes nothing,
    and its worst size is zero: a caller writing that to standard output writes nothing, succeeds,
    and reports success, which is the one outcome that tells a reader there is nothing to look into.
    So the third is made to announce itself like the other two, here, where the description is read
    and where the fault belongs to elenctic's own packaging rather than to any caller.

    The version is in the resource's name rather than beside it, because the shape of a document and
    the description of that shape are one fact. A bump that renamed the constant and not the file
    would otherwise go on printing the description of a document the package no longer produces;
    this way it finds nothing, and a copy of the package missing the file at all is reported the
    same way — as elenctic's own fault, which is what a packaging fault is.

    **A release carries exactly one of these**, and a bump deletes the file it supersedes rather
    than shipping both. What a superseded description would be for is reading a document an older
    build wrote — and the release that wrote it still carries its own, so keeping a copy here would
    put a second answer in the package to a question this package is not where anyone should ask.
    It is also what keeps the constant the only thing a bump has to touch: there is no set of
    supported versions to hold in step, and no policy owed about which of them are still served.
    """
    resource = files("elenctic") / "schema" / f"output-v{SCHEMA_VERSION}.schema.json"
    # The bytes, decoded here, rather than a text read. Reading a resource as text opens it in
    # universal-newline mode, which turns a CRLF file back into LF on the way through — so "exactly
    # as it ships" was false for any checkout or archive that gave the file those endings, by
    # precisely the bytes someone diffing this output against the published file would see. Decoding
    # what was read keeps the claim true and keeps the fault a mis-encoded file raises.
    description = resource.read_bytes().decode("utf-8")
    # It parses, and no more than that. Whether the description is a *well-formed schema* is a
    # different question with a different owner — it is settled once, against the file that ships,
    # rather than re-asked of every reader at run time — and elenctic is not a schema validator.
    # What this separates is a description from a fragment of one, which is the whole of the damage
    # a truncation does.
    json.loads(description)
    return description


def _case(outcome: CaseOutcome) -> dict[str, object]:
    return {
        "source": _text(outcome.case.contract_source),
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
        # Beside the file rather than spelled into the message, on the same terms a check's line is:
        # a consumer placing a diagnostic reads a number, and a message it would have to parse one
        # out of is a message it is not allowed to depend on. Null where the fault names no single
        # line, which is most of them.
        "line": record.line,
        "message": _text(record.message),
    }


def _hygiene(record: HygieneRecord) -> dict[str, object]:
    return {
        "kind": record.kind.value,
        "grade": record.grade.value,
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
