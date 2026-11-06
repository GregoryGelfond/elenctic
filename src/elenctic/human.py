"""The human view of a run: text for a terminal, verdicts and summary apart from diagnostics.

Everything a program contributes is made legible before it is styled, so no program can steer the
terminal, and the styling that follows is never escaped.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum, auto
from pathlib import Path
from typing import Final

from elenctic.about import Package, Solvers
from elenctic.determination import Truncation, option
from elenctic.display import legible
from elenctic.glyphs import COPYRIGHT, MARKS
from elenctic.paint import Role, paint
from elenctic.presentation import Presentation, Style
from elenctic.program import Fault
from elenctic.report import Entry, Internal, Run
from elenctic.spans import Child, Diagnostic, Severity, Span
from elenctic.verdicts import Ended, Finding, Report, Verdict

VERDICT_ROLES: Final[Mapping[Verdict, Role]] = {
    Verdict.PASS: Role.NOTE,
    Verdict.FAIL: Role.ERROR,
    Verdict.UNDECIDED: Role.WARNING,
}
SEVERITY_ROLES: Final[Mapping[Severity, Role]] = {
    Severity.ERROR: Role.ERROR,
    Severity.WARNING: Role.WARNING,
    Severity.NOTE: Role.NOTE,
    Severity.HELP: Role.HELP,
}
CUT_WORDS: Final[Mapping[Truncation, str]] = {
    Truncation.MAX_ANSWER_SETS: f"answer-set limit reached ({option(Truncation.MAX_ANSWER_SETS)})",
    Truncation.MAX_SECONDS: f"time limit reached ({option(Truncation.MAX_SECONDS)})",
    Truncation.INTERRUPTED: "interrupted",
}


class Format(StrEnum):
    """How diagnostics are written for a human."""

    FULL = auto()
    SHORT = auto()


@dataclass(frozen=True, slots=True)
class Rendered:
    """A run as text, each line ending in a newline: verdicts and summary, and diagnostics."""

    stdout: str
    stderr: str


def _say(style: Style, role: Role, text: str) -> str:
    """Untrusted `text`, made legible and then styled; styling is never escaped."""
    return paint(style.color, role, legible(text))


def _detail(detail: str | Ended) -> str:
    """Word what was found, or what cut the search short."""
    match detail:
        case Ended(cut, optimum_unproven):
            unproven = "no optimum proven: " if optimum_unproven else ""
            return f"{unproven}search ended: {CUT_WORDS[cut]}"
        case _:
            return legible(detail)


def _line(finding: Finding, style: Style) -> str:
    verdict = finding.verdict
    mark = paint(style.color, VERDICT_ROLES[verdict], MARKS[verdict].shown(style.glyphs))
    line = paint(style.color, Role.MARGIN, f"(line {finding.claim.span.start.line})")
    return f"  {mark} {legible(finding.claim_text)} {line}: {_detail(finding.detail)}"


def _header(diagnostic: Diagnostic, style: Style) -> str:
    severity = paint(style.color, SEVERITY_ROLES[diagnostic.severity], diagnostic.severity.value)
    return f"{severity}: {_say(style, Role.EMPHASIS, diagnostic.message)}"


def _short(diagnostic: Diagnostic, style: Style, source: str | None = None) -> str:
    """Today's one-line form: `path:l:c-c: level: message` when located."""
    severity = paint(style.color, SEVERITY_ROLES[diagnostic.severity], diagnostic.severity.value)
    message = legible(diagnostic.message)
    if diagnostic.span is None:
        if source:
            return f"{_say(style, Role.EMPHASIS, legible(source))}: {severity}: {message}"
        return f"{severity}: {message}"
    where = _say(style, Role.EMPHASIS, str(diagnostic.span))
    return f"{where}: {severity}: {message}"


def _margin(style: Style, text: str) -> str:
    return paint(style.color, Role.MARGIN, text)


def _caret_line(span: Span, label: str, style: Style, role: Role) -> str:
    width = max(1, span.end.column - span.start.column) if span.end.line == span.start.line else 1
    carets = paint(style.color, role, "^" * width)
    pad = " " * (span.start.column - 1)
    marked = f"{pad}{carets}"
    if not label:
        return f"{_margin(style, '  |')} {marked}"
    return f"{_margin(style, '  |')} {marked} {legible(label)}"


def _file_text(span: Span, text: str | None) -> str | None:
    """Return text for `span.source`, reading the file when it is on disk."""
    try:
        path = Path(span.source)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except OSError:
        pass
    return text


def _snippet(diagnostic: Diagnostic, text: str | None, style: Style) -> list[str]:
    span = diagnostic.span
    if span is None:
        return []
    arrow = _margin(style, f" --> {legible(span.source)}:{span.start.line}:{span.start.column}")
    source_text = _file_text(span, text)
    if source_text is None:
        return [arrow]
    lines = source_text.split("\n")
    if not (1 <= span.start.line <= len(lines)):
        return [arrow]
    source_line = lines[span.start.line - 1]
    number = str(span.start.line)
    gutter = _margin(style, f"{number} |")
    role = SEVERITY_ROLES[diagnostic.severity]
    return [
        arrow,
        _margin(style, "  |"),
        f"{gutter} {legible(source_line)}",
        _caret_line(span, diagnostic.label, style, role),
    ]


def _child_lines(children: tuple[Child, ...], style: Style) -> list[str]:
    lines: list[str] = []
    for child in children:
        role = SEVERITY_ROLES[child.severity]
        label = paint(style.color, role, f"= {child.severity.value}:")
        lines.append(f"{_margin(style, '  |')}")
        lines.append(f"  {label} {legible(child.message)}")
    return lines


def _full(
    diagnostic: Diagnostic, text: str | None, style: Style, source: str | None = None
) -> list[str]:
    """Render the rustc multi-line form: header, location, snippet, notes and help."""
    lines = [_header(diagnostic, style)]
    if diagnostic.span is not None:
        lines.extend(_snippet(diagnostic, text, style))
    elif source:
        lines.append(_margin(style, f" --> {legible(source)}"))
    lines.extend(_child_lines(diagnostic.children, style))
    return lines


def _diagnostic_lines(
    diagnostic: Diagnostic,
    text: str | None,
    style: Style,
    form: Format,
    source: str | None = None,
) -> list[str]:
    if form is Format.SHORT:
        return [_short(diagnostic, style, source)]
    return _full(diagnostic, text, style, source)


def _fault(
    fault: Fault, text: str | None, style: Style, form: Format, source: str | None = None
) -> list[str]:
    lines = [
        line
        for diagnostic in fault.diagnostics
        for line in _diagnostic_lines(diagnostic, text, style, form, source)
    ]
    return lines or [str(fault.locus)]


def _entry(entry: Entry, style: Style, *, verbose: bool) -> list[str]:
    match entry.result:
        case Report(source=source, findings=findings) as report if (
            verbose or report.verdict is not Verdict.PASS
        ):
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


def render_run(
    run: Run,
    presentation: Presentation,
    *,
    verbose: bool = False,
    form: Format = Format.FULL,
) -> Rendered:
    """Write a run as text: each source that did not pass, with its claims that did not.

    The faults, which keep a source from being checked, are the diagnostics. Notes on queries
    that read a hidden literal are diagnostics too, and do not change the exit. `form` chooses
    the rustc multi-line form or today's one-line short form.
    """
    stdout, stderr = presentation.stdout, presentation.stderr
    shown = [line for entry in run.entries for line in _entry(entry, stdout, verbose=verbose)]
    notes = [
        line
        for entry in run.entries
        if isinstance(entry.result, Report)
        for lint in entry.result.lints
        for line in _diagnostic_lines(lint, entry.text, stderr, form)
    ]
    notes += [
        line
        for diagnostic in run.notes
        for line in _diagnostic_lines(diagnostic, None, stderr, form)
    ]
    faults = [
        line
        for entry in run.entries
        if isinstance(entry.result, Fault)
        for line in _fault(entry.result, entry.text, stderr, form, entry.source)
    ]
    internals = [
        internal_error(entry.result, stderr).rstrip("\n")
        for entry in run.entries
        if isinstance(entry.result, Internal)
    ]
    return Rendered(_lines([*shown, _summary(run, stdout)]), _lines([*notes, *faults, *internals]))


def reserved(command: str, style: Style) -> str:
    """Write the note on a command kept for later."""
    return (
        paint(style.color, Role.HELP, f"elenctic: `{command}` is reserved and not yet built") + "\n"
    )


def internal_error(error: Exception | Internal, style: Style) -> str:
    """Write the one line for a failure of elenctic itself."""
    if isinstance(error, Internal):
        name, message = error.error_type, error.message
    else:
        name, message = type(error).__name__, str(error)
    return _say(style, Role.ERROR, f"elenctic: internal error: {name}: {message}") + "\n"


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
