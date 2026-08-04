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
from pathlib import Path
from typing import Any, NamedTuple

from elenctic.result import Conclusion, Determination, SolveOutcome

__all__ = [
    "Streams",
    "child_environment",
    "cli_help_sections",
    "cli_help_text",
    "decided",
    "document_of",
    "run_cli",
]

# How long a child may take before it is a hang rather than a slow run. It has to exceed the largest
# ``--budget`` any test asks for, multiplied by the largest corpus any test builds, with room for
# the interpreter to start; a number without that reasoning beside it is one nobody can safely
# change.
_CHILD_TIMEOUT_SECONDS = 300


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
    """
    environment = {**os.environ, **(env or {})}
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
    import elenctic.cli

    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            _CHILD.format(prelude=prelude, loaded=elenctic.cli.__file__),
            str(target),
            *flags,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=_CHILD_TIMEOUT_SECONDS,
        check=False,
        env=child_environment(env, hash_seed),
    )
    return Streams(finished.stdout, finished.stderr, finished.returncode)


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

    with contextlib.redirect_stdout(written):
        try:
            main(["--help"])
        except SystemExit as leaving:
            assert leaving.code == 0, f"asking for the help left with {leaving.code}"
        else:  # pragma: no cover — argparse leaves by raising; reached only if that changes
            raise AssertionError("--help returned instead of leaving")
    return written.getvalue()


def cli_help_sections() -> dict[str, list[str]]:
    """``--help`` split at its headings: each heading mapped to the lines filed under it.

    A heading is what ``argparse`` writes at column zero ending in a colon. Reading the help by its
    structure rather than by searching the whole text is what keeps an assertion about one section
    from being answered by a coincidence in another — a wrapped line of one option's help can begin
    with a digit, and read as a documented exit status.
    """
    filed: dict[str, list[str]] = {}
    under: list[str] = []
    for line in cli_help_text().splitlines():
        if line and not line[0].isspace() and line.rstrip().endswith(":"):
            under = filed.setdefault(line.rstrip().removesuffix(":"), [])
        else:
            under.append(line)
    return filed


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
