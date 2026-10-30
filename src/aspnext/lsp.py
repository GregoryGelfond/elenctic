"""Language Server Protocol diagnostics from a result; the server around it is not written yet."""

from enum import IntEnum

from aspnext.check import Report, Verdict
from aspnext.engine import Fault
from aspnext.spans import Diagnostic, Position, Severity, Span

type Lsp = dict[str, object]


class Level(IntEnum):
    ERROR = 1
    WARNING = 2
    INFORMATION = 3


_SEVERITY = {
    Severity.ERROR: Level.ERROR,
    Severity.WARNING: Level.WARNING,
    Severity.NOTE: Level.INFORMATION,
}
_VERDICT = {Verdict.FAIL: Level.ERROR, Verdict.UNDECIDED: Level.WARNING}


def _position(position: Position) -> Lsp:
    return {"line": position.line - 1, "character": position.column - 1}


def _range(span: Span) -> Lsp:
    return {"start": _position(span.start), "end": _position(span.end)}


def _diagnostic(span: Span, level: Level, message: str) -> Lsp:
    return {"range": _range(span), "severity": int(level), "message": message, "source": "aspnext"}


def diagnostics(result: Report | Fault) -> list[Lsp]:
    """LSP diagnostics: a fault's own, or one per claim that did not pass."""
    if isinstance(result, Fault):
        return [_diagnostic(d.span, _SEVERITY[d.severity], d.message) for d in result.diagnostics]
    return [
        _diagnostic(f.claim.span, _VERDICT[f.verdict], f"{f.claim_text}: {f.detail}")
        for f in result.findings
        if f.verdict is not Verdict.PASS
    ]


def contract_diagnostics(found: tuple[Diagnostic, ...]) -> list[Lsp]:
    return [_diagnostic(d.span, _SEVERITY[d.severity], d.message) for d in found]
