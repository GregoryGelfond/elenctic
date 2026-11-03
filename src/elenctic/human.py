"""The human view of a run: text for a terminal, verdicts and summary apart from diagnostics.

Everything a program contributes is made legible before it is styled, so no program can steer the
terminal, and the styling that follows is never escaped.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from elenctic.about import Package, Solvers
from elenctic.display import legible
from elenctic.glyphs import COPYRIGHT, MARKS
from elenctic.paint import Role, paint
from elenctic.presentation import Presentation, Style
from elenctic.program import Fault
from elenctic.report import Entry, Run
from elenctic.spans import Diagnostic, Severity
from elenctic.verdicts import Finding, Report, Verdict

VERDICT_ROLES: Final[Mapping[Verdict, Role]] = {
    Verdict.PASS: Role.NOTE,
    Verdict.FAIL: Role.ERROR,
    Verdict.UNDECIDED: Role.WARNING,
}
SEVERITY_ROLES: Final[Mapping[Severity, Role]] = {
    Severity.ERROR: Role.ERROR,
    Severity.WARNING: Role.WARNING,
    Severity.NOTE: Role.NOTE,
}


@dataclass(frozen=True, slots=True)
class Rendered:
    """A run as text, each line ending in a newline: verdicts and summary, and diagnostics."""

    stdout: str
    stderr: str


def _say(style: Style, role: Role, text: str) -> str:
    """Untrusted `text`, made legible and then styled; styling is never escaped."""
    return paint(style.color, role, legible(text))


def _line(finding: Finding, style: Style) -> str:
    verdict = finding.verdict
    mark = paint(style.color, VERDICT_ROLES[verdict], MARKS[verdict].shown(style.glyphs))
    line = paint(style.color, Role.MARGIN, f"(line {finding.claim.span.start.line})")
    return f"  {mark} {legible(finding.claim_text)} {line}: {legible(finding.detail)}"


def _diagnostic(diagnostic: Diagnostic, style: Style) -> str:
    where = _say(style, Role.EMPHASIS, str(diagnostic.span))
    severity = paint(style.color, SEVERITY_ROLES[diagnostic.severity], diagnostic.severity.value)
    return f"{where}: {severity}: {legible(diagnostic.message)}"


def _fault(fault: Fault, style: Style) -> list[str]:
    return [_diagnostic(d, style) for d in fault.diagnostics] or [str(fault.locus)]


def _entry(entry: Entry, style: Style, *, verbose: bool) -> list[str]:
    match entry.result:
        case Report(source, findings) as report if verbose or report.verdict is not Verdict.PASS:
            shown = [f for f in findings if verbose or f.verdict is not Verdict.PASS]
            verdict = paint(style.color, VERDICT_ROLES[report.verdict], report.verdict.name)
            return [
                f"{_say(style, Role.EMPHASIS, source)} — {verdict}",
                *(_line(finding, style) for finding in shown),
                "",
            ]
        case _:
            return []


def _summary(run: Run, style: Style) -> str:
    reports = [e.result for e in run.entries if isinstance(e.result, Report)]
    counts = {v: sum(r.verdict is v for r in reports) for v in Verdict}
    faults = len(run.entries) - len(reports)
    tail = [
        (VERDICT_ROLES[v], f"{counts[v]} {v.value}")
        for v in (Verdict.FAIL, Verdict.UNDECIDED)
        if counts[v]
    ]
    tail += [(Role.ERROR, f"{faults} error")] if faults else []
    passed = paint(style.color, Role.EMPHASIS, f"{counts[Verdict.PASS]}/{len(run.entries)} passed")
    return passed + "".join(f", {paint(style.color, role, text)}" for role, text in tail)


def _lines(lines: list[str]) -> str:
    return "".join(f"{line}\n" for line in lines)


def render(run: Run, presentation: Presentation, *, verbose: bool = False) -> Rendered:
    """Write a run as text: each source that did not pass, with its claims that did not.

    The faults, which keep a source from being checked, are the diagnostics.
    """
    stdout, stderr = presentation.stdout, presentation.stderr
    shown = [line for entry in run.entries for line in _entry(entry, stdout, verbose=verbose)]
    faults = [
        line
        for entry in run.entries
        if isinstance(entry.result, Fault)
        for line in _fault(entry.result, stderr)
    ]
    return Rendered(_lines([*shown, _summary(run, stdout)]), _lines(faults))


def reserved(command: str, style: Style) -> str:
    """Write the note on a command kept for later."""
    return paint(style.color, Role.HELP, f"elenctic: `{command}` is reserved and not yet built")


def internal_error(error: Exception, style: Style) -> str:
    """Write the one line for a failure of elenctic itself."""
    return _say(style, Role.ERROR, f"elenctic: internal error: {type(error).__name__}: {error}")


def version(package: Package, solvers: Solvers, style: Style) -> str:
    """Write the version text: the package and its copyright line, then the solvers loaded.

    The fields are made legible and the glyph is added after, as it would not survive that. The
    text is plain: it names no role, so `--color` leaves it alone.
    """
    mark = COPYRIGHT.shown(style.glyphs)
    holder = f"{mark} {package.year} {legible(package.holder)}"
    clingcon = "not installed" if solvers.clingcon is None else legible(solvers.clingcon)
    return _lines(
        [
            f"elenctic {legible(package.version)} | {holder} | {legible(package.license)}",
            f"clingo {legible(solvers.clingo)} | clingcon {clingcon}",
        ]
    )
