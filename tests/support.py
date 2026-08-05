"""Shared test scaffolding.

Importable from any test module because ``pythonpath`` puts this directory on the path; ``conftest``
itself is not importable under pytest's importlib mode, so shared helpers live here instead.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from clingo import Control

from elenctic.result import Conclusion, Determination, SolveOutcome

__all__ = [
    "Streams",
    "a_clock_the_deadline_has_already_passed_on",
    "child_environment",
    "cli_help_section",
    "cli_help_sections",
    "cli_help_text",
    "decided",
    "document_of",
    "opt_mode_in_force",
    "run_cli",
    "run_cli_with_neither_stream_reachable",
    "run_cli_with_nobody_reading",
    "run_cli_with_nobody_reading_diagnostics",
    "run_cli_without_standard_error",
    "run_cli_without_standard_output",
    "without_standard_error",
]

# How long a child may take before it is a hang rather than a slow run. It has to exceed the largest
# ``--budget`` any test asks for, multiplied by the largest corpus any test builds, with room for
# the interpreter to start; a number without that reasoning beside it is one nobody can safely
# change.
_CHILD_TIMEOUT_SECONDS = 300


def opt_mode_in_force(control: Control) -> str:
    """The optimization setting ``control`` will solve under — read back off the configuration
    rather than inferred from the flags or the call that set it, because the configuration is what
    the solver consults. clingo's configuration proxy is dynamically typed, the same boundary
    ``solvers._set_opt_mode`` isolates for the write, so the narrowing lives here once instead of at
    each reading."""
    return str(control.configuration.solve.opt_mode)  # type: ignore[union-attr]


def decided(determination: Determination) -> SolveOutcome:
    """A determination as a *finished* search reported it.

    The frame a check test is written in unless the test is about a search that stopped early —
    those state the conclusion they mean, in ``test_partial_search_verdicts.py``. It applies to the
    undecided arm too: a search can close the space and still leave the mode nothing to build from,
    and that pairing is the one whose diagnostic has no remedy to offer.
    """
    return SolveOutcome(determination, Conclusion.EXHAUSTED)


# The child: elenctic's own console entry, given the arguments the parent passes after the program
# text, and made to prove first that it is the same copy of the package the parent is testing. A
# prelude may stand a fault in front of it, which is how a register only a fault can reach gets
# exercised without one being contrived inside a corpus.
_CHILD = """
import sys
{prelude}
import elenctic.cli
from elenctic.cli import main

if elenctic.cli.__file__ != {loaded!r}:
    raise SystemExit("the child loaded " + str(elenctic.cli.__file__) + ", not the tree under test")
sys.exit(main(sys.argv[1:]))
"""


class Streams(NamedTuple):
    """What one run of the command line put on each stream, and the status it left with."""

    out: str
    err: str
    status: int


def child_environment(
    env: dict[str, str] | None = None, hash_seed: str | None = None
) -> dict[str, str]:
    """The environment a child is given, as a value, so that what it does to the hash seed is
    something a test can look at rather than something it has to believe.

    ``hash_seed`` is set explicitly when given and cleared otherwise. Clearing it means the child
    picks its own, which is what makes two runs two seeds; *inheriting* it would mean two runs under
    whatever single seed the parent happened to have, and a comparison of two such runs is a run
    compared against itself — anything ordered by a hash would survive it.

    ``PYTHONUNBUFFERED`` is cleared for a different reason and can be set back through ``env``. It
    decides whether the child's standard output hands each write straight to the descriptor or holds
    it, which decides *when* a write to a stream nobody is reading fails — and that is the axis
    several measurements here are about. Inherited, a developer's shell or a CI image would be
    setting it, so a run could take a different path on one machine than on another and say nothing
    about it.
    """
    environment = {**os.environ, **(env or {})}
    environment.pop("PYTHONUNBUFFERED", None)
    environment.update(env or {})
    if hash_seed is None:
        environment.pop("PYTHONHASHSEED", None)
    else:
        environment["PYTHONHASHSEED"] = hash_seed
    return environment


def run_cli(
    target: Path,
    *flags: str,
    prelude: str = "",
    env: dict[str, str] | None = None,
    hash_seed: str | None = None,
) -> Streams:
    """One invocation of elenctic, **as a process**, with its two streams kept apart.

    A process and not a call, wherever what is being tested is which stream something landed on.
    Standard output carries the machine-readable report because the descriptor it *is* has been
    moved; a test runner capturing output replaces this language's standard output with an object of
    its own writing to a file of its own, which no longer travels through that descriptor. An
    in-process test therefore watches a stream the guarantee never touches, and reports a clean
    standard output whether or not the guarantee holds. Both capture fixtures share that blind spot.

    Both streams are decoded as UTF-8 here whatever the child was asked to encode in, because what
    the child encodes in is itself under test in places. Decoding strictly is safe for standard
    error only because this interpreter fixes that stream's error handler to ``backslashreplace``;
    without that, a child writing a diagnostic it could not encode would take the runner down
    instead of failing the test.

    ``elenctic.cli`` is imported here rather than at module scope so that the helpers above, which
    need nothing from the console entry, do not drag its whole import graph — and the package's
    lazy attribute resolution — into every test session that wants them.
    """
    finished = subprocess.run(
        _child_command(target, flags, prelude),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_CHILD_TIMEOUT_SECONDS,
        check=False,
        env=child_environment(env, hash_seed),
    )
    return Streams(finished.stdout, finished.stderr, finished.returncode)


def _child_command(target: Path, flags: tuple[str, ...], prelude: str) -> list[str]:
    """The command that runs elenctic's console entry as a child process.

    Shared by every way a run is spawned below, because the part that must not vary between them is
    the child's proof that it loaded the tree under test: an instrument measuring a different
    installation reports on code nobody changed, and says nothing while doing it.
    """
    import elenctic.cli

    return [
        sys.executable,
        "-c",
        _CHILD.format(prelude=prelude, loaded=elenctic.cli.__file__),
        str(target),
        *flags,
    ]


def _with_stream_closed(descriptor: int, command: list[str]) -> list[str]:
    """``command``, arranged so that ``descriptor`` is **closed** — gone, not pointed elsewhere —
    before the program starts.

    A shell closes it and then hands the process over, so the condition is established ahead of the
    program and this process is never left in it. ``subprocess`` has no way to ask for this: every
    value it takes for a stream leaves the descriptor open on something.

    That distinction is the whole measurement. A stream that is merely *redirected* — to a pipe, to
    a file, to the null device — is still there, and everything behaves. One that is gone is a
    stream this language leaves unbuilt, so writes to it go wherever the fallback goes, and the
    number it no longer holds is free to be handed out to something else. Anything that starts a
    process on your behalf keeps both streams open, so a reading taken through one is a reading of
    a run that never met the condition.
    """
    return ["sh", "-c", f'exec "$@" {descriptor}>&-', "sh", *command]


def without_standard_error(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``command`` with standard error closed, capturing what it puts on standard output."""
    return subprocess.run(
        _with_stream_closed(2, command),
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=_CHILD_TIMEOUT_SECONDS,
        check=False,
        env=child_environment(),
    )


def run_cli_without_standard_error(target: Path, *flags: str, prelude: str = "") -> tuple[str, int]:
    """One invocation of elenctic that has no standard error: what reached standard output, and the
    status it left with.

    Two values rather than three, because there is no third stream for one to be about.
    """
    finished = without_standard_error(_child_command(target, flags, prelude))
    return finished.stdout, finished.returncode


def run_cli_without_standard_output(
    target: Path, *flags: str, prelude: str = ""
) -> tuple[str, int]:
    """One invocation of elenctic that has no standard output: what it said on standard error, and
    the status it left with.

    The other half of the pair above, and not the same condition read from the other end: a run with
    no standard error has nowhere to put its diagnostics, and a run with no standard output has
    nothing to publish at all.
    """
    finished = subprocess.run(
        _with_stream_closed(1, _child_command(target, flags, prelude)),
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=_CHILD_TIMEOUT_SECONDS,
        check=False,
        env=child_environment(),
    )
    return finished.stderr, finished.returncode


def run_cli_with_nobody_reading(target: Path, *flags: str, prelude: str = "") -> tuple[str, int]:
    """One invocation of elenctic whose standard output is a pipe with **no reader** on it: what it
    said on standard error, and the status it left with.

    The read end is closed **before the child exists**, so the pipe has no reader for a single
    instant of its life and the first write to reach the descriptor fails. Piping into a command
    that exits — ``| head -1`` — raises the same exception, but it is not the same situation: a real
    reader drains up to the pipe's capacity before it goes, so a run whose whole output fits never
    breaks the pipe at all. This is the stronger relative, chosen because it arrives at a moment a
    test can name rather than whenever the buffers decide.

    Two values again, and this time it is standard output that is missing: whatever the run put
    there went nowhere, which is the condition under test.
    """
    read_end, write_end = os.pipe()
    # Before the child is started, not after it returns: a read end still open across the fork is a
    # reader, however briefly, and "no reader" would then be an argument about timing rather than
    # something arranged.
    os.close(read_end)
    try:
        child = subprocess.Popen(
            _child_command(target, flags, prelude),
            stdout=write_end,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=child_environment(),
        )
    finally:
        os.close(write_end)
    with child:
        said = child.communicate(timeout=_CHILD_TIMEOUT_SECONDS)[1]
    return said, child.returncode


def run_cli_with_nobody_reading_diagnostics(
    target: Path, *flags: str, report: Path, prelude: str = ""
) -> tuple[str, int]:
    """One invocation whose standard **error** is a pipe with no reader, while standard output is a
    real file being kept: what that file ended up holding, and the status the run left with.

    The mirror of the pair above, and the one that catches a frame answering about the wrong stream.
    Here the reader who went away is standard error's, and standard output is healthy — so anything
    that treats a broken pipe as a fact about standard output empties a file its reader was keeping.
    """
    read_end, write_end = os.pipe()
    os.close(read_end)
    with report.open("wb") as kept:
        try:
            child = subprocess.Popen(
                _child_command(target, flags, prelude),
                stdout=kept,
                stderr=write_end,
                env=child_environment(),
            )
        finally:
            os.close(write_end)
        with child:
            child.wait(timeout=_CHILD_TIMEOUT_SECONDS)
    return report.read_text(encoding="utf-8"), child.returncode


def run_cli_with_neither_stream_reachable(target: Path, *flags: str) -> int:
    """One invocation with standard error **closed** and no reader on standard output: the status,
    and nothing else, because nothing else survives.

    The two conditions the helpers above arrange separately, met together — which is the shape a
    consumer reaches by silencing the diagnostics and then piping the report into something that
    stops reading. Nothing elenctic says can be seen, so the status is the entire signal and the
    only thing there is to assert.
    """
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        child = subprocess.Popen(
            _with_stream_closed(2, _child_command(target, flags, "")),
            stdout=write_end,
            env=child_environment(),
        )
    finally:
        os.close(write_end)
    with child:
        child.wait(timeout=_CHILD_TIMEOUT_SECONDS)
    return child.returncode


def cli_help_text() -> str:
    """What ``elenctic --help`` writes, having left with the status that says nothing went wrong.

    A call rather than a process, and rebinding the stream rather than the descriptor, because
    ``--help`` is answered inside ``parse_args`` and leaves from there — it never reaches the region
    where standard output is a descriptor, which is what forces the machine-readable tests to spawn
    a child. It lives here because the help is read by tests of two different subjects: what the
    help *is*, and whether what it says about the exit status is what the ladder produces.
    """
    written = io.StringIO()
    from elenctic.cli import main

    # `pytest.raises` rather than a try/except pair, and it says both halves at once: that asking
    # for the help *leaves* rather than returning is the failure the `else` branch used to catch,
    # and it is what this refuses to pass without.
    with contextlib.redirect_stdout(written), pytest.raises(SystemExit) as leaving:
        main(["--help"])
    assert leaving.value.code == 0, f"asking for the help left with {leaving.value.code}"
    return written.getvalue()


def a_clock_the_deadline_has_already_passed_on(deadline: float) -> Callable[[], float]:
    """A monotonic clock that says ``deadline`` seconds went by between starting the run and
    reaching the first case.

    The deadline is a duration rather than an instant, so forcing one to have passed means
    controlling the clock and not the number: an invocation refuses a zero on the same footing as
    the published description of the document does, so there is no number that has already elapsed
    when the first case is reached, and asking for one short enough would make the test a race
    against how long two statements take.

    The second reading is the deadline itself rather than a number past it, because that is the
    point the run branches at — a reading safely beyond it would pass under either comparison and
    say nothing about which one the code makes.
    """
    readings = iter((0.0, deadline))
    return lambda: next(readings, deadline)


def cli_help_sections() -> dict[str, list[str]]:
    """``--help`` split at its headings: each heading mapped to the lines filed under it.

    A heading is what ``argparse`` writes at column zero ending in a colon. Reading the help by its
    structure rather than by searching the whole text is what keeps an assertion about one section
    from being answered by a coincidence in another — a wrapped line of one option's help can begin
    with a digit, and read as a documented exit status.
    """
    filed: dict[str, list[str]] = {}
    under: list[str] = []
    lines = cli_help_text().splitlines()
    for index, line in enumerate(lines):
        if (
            line
            and not line[0].isspace()
            and line.rstrip().endswith(":")
            and _indented_next(lines, index)
        ):
            under = filed.setdefault(line.rstrip().removesuffix(":"), [])
        else:
            under.append(line)
    return filed


def cli_help_section(prefix: str) -> list[str]:
    """The lines under the one ``--help`` heading beginning with ``prefix``.

    By prefix rather than by exact title, so that a heading may say more about itself without every
    reader of it having to be told. Exactly one must match: a prefix answering to two headings is a
    reading that would silently pick whichever came first.
    """
    matched = {
        heading: lines
        for heading, lines in cli_help_sections().items()
        if heading.startswith(prefix)
    }
    assert len(matched) == 1, f"{prefix!r} matched {sorted(matched)}"
    return next(iter(matched.values()))


def _indented_next(lines: list[str], index: int) -> bool:
    """Whether the next line with anything on it is indented under ``lines[index]``.

    What tells a heading from a sentence that happens to end in a colon. Without it, a paragraph of
    prose introducing a list — which is a shape English produces constantly — is read as a heading,
    and everything after it is filed away from the section it belongs to. That is not hypothetical:
    it is how the one paragraph saying what a refused command line returns came to sit outside the
    section a test reads to check those numbers.
    """
    return next(
        (line.startswith(" ") for line in lines[index + 1 :] if line.strip()),
        False,
    )


def document_of(streams: Streams) -> dict[str, Any]:
    """What standard output carried, parsed — with the run's own account of itself if it carried no
    document, since a child that died for an unrelated reason otherwise reports only that something
    was not JSON."""
    try:
        parsed = json.loads(streams.out)
    except json.JSONDecodeError as broken:
        raise AssertionError(
            f"standard output carried no document ({broken}). The run exited "
            f"{streams.status} and said:\n{streams.err}"
        ) from broken
    if not isinstance(parsed, dict):
        # JSON, but not a document. Caught here rather than left to fail on the first subscript,
        # where it arrives as a TypeError about the wrong thing.
        raise AssertionError(f"standard output carried {parsed!r}, which is JSON but not an object")
    document: dict[str, Any] = parsed
    return document
