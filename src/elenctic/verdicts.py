"""The verdict on a claim, and the finding and the report that carry it."""

from dataclasses import dataclass
from enum import StrEnum, auto

from elenctic.contract import Claim
from elenctic.writer import render


class Verdict(StrEnum):
    PASS = auto()
    FAIL = auto()
    UNDECIDED = auto()

    @staticmethod
    def when(*, holds: bool) -> Verdict:
        """Settle a claim that is decided by what is found: it passes if it holds, else fails."""
        return Verdict.PASS if holds else Verdict.FAIL


@dataclass(frozen=True, slots=True)
class Finding:
    """A claim, the verdict on it, and what was expected against what was found."""

    claim: Claim
    verdict: Verdict
    detail: str

    @property
    def claim_text(self) -> str:
        return render(self.claim)


@dataclass(frozen=True, slots=True)
class Report:
    source: str
    findings: tuple[Finding, ...]

    @property
    def verdict(self) -> Verdict:
        """Fail if any claim fails, else undecided if any is, else pass."""
        verdicts = {f.verdict for f in self.findings}
        return next((v for v in (Verdict.FAIL, Verdict.UNDECIDED) if v in verdicts), Verdict.PASS)


def existential(*, found: bool, closed: bool) -> Verdict:
    """Settle a claim an answer set can witness: one upholds it, only a closed search refutes it."""
    return Verdict.PASS if found else Verdict.FAIL if closed else Verdict.UNDECIDED


def universal(*, refuted: bool, closed: bool) -> Verdict:
    """Settle a claim an answer set can refute: one refutes it, only a closed search upholds it."""
    return Verdict.FAIL if refuted else Verdict.PASS if closed else Verdict.UNDECIDED
