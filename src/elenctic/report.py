"""The result of a run, as plain values: what each source came to, and how the run exits."""

from dataclasses import dataclass
from enum import IntEnum

from elenctic.program import Fault
from elenctic.verdicts import Report, Verdict


class Exit(IntEnum):
    """The status a run exits with; CI reads it, so the values are fixed."""

    CLAIMS_HOLD = 0
    """Every claim passed."""
    CLAIM_UNMET = 1
    """Some claim failed or was undecided."""
    FAULT = 2
    """Some source could not be checked, or the command was refused."""
    INTERNAL_ERROR = 3
    """elenctic itself failed: an exception that no check anticipated."""


@dataclass(frozen=True, slots=True)
class Entry:
    """What checking one source came to."""

    source: str
    result: Report | Fault


@dataclass(frozen=True, slots=True)
class Run:
    """What checking each source came to."""

    entries: tuple[Entry, ...]

    @property
    def exit_code(self) -> Exit:
        """A fault if any source could not be checked, else a failure unless every claim passed."""
        results = [entry.result for entry in self.entries]
        if any(isinstance(result, Fault) for result in results):
            return Exit.FAULT
        unmet = any(r.verdict is not Verdict.PASS for r in results if isinstance(r, Report))
        return Exit.CLAIM_UNMET if unmet else Exit.CLAIMS_HOLD
