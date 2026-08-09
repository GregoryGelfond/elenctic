"""The streams a program is owed: the standard error it asks for on the way in, and the standard
output it hands over on the way out.

Every entry point asks the first rule before it writes anything, so what it guarantees on return is
what five programs depend on. It is two guarantees, not one, and they fail independently:

- **``sys.stderr`` is a stream.** Where it is ``None`` — which is what this language leaves when the
  descriptor was closed at start-up — ``print(..., file=sys.stderr)`` writes to standard *output*,
  and a diagnostic lands in the middle of whatever the run was publishing.
- **Descriptor 2 is open.** A closed descriptor is the lowest free number, so it is the next one
  handed out; the copy of standard output that the machine-readable path takes on its way in would
  *become* descriptor 2, and the redirect would then point standard output at itself.

Those two are a process each, because both conditions are properties of a process's descriptor table
and neither can be arranged inside a test runner that has replaced the streams with objects of its
own. The hand-over below is not: what it is about is the two *layers* of one stream, which a real
file has and a capture fixture's single object does not.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from elenctic.streams import hand_over_standard_output
from support import without_standard_error

# Something already holding descriptor 2 by the time the rule runs. Any import that leaves a file
# open does this — the descriptor was closed, so its number is the first one free. It is written as
# an explicit open rather than by finding an import that happens to do it today, because what is
# under test is the rule, not the import graph of whatever elenctic depends on this month.
_SOMETHING_HOLDS_DESCRIPTOR_2 = "held = os.open(os.devnull, os.O_WRONLY)\nassert held == 2\n"

_ASK_THE_RULE = """
import os, sys
{taken}
from elenctic.streams import establish_standard_error

establish_standard_error()
print("stream" if sys.stderr is not None else "none")
print("A DIAGNOSTIC", file=sys.stderr)
"""


def _child(taken: str = "") -> subprocess.CompletedProcess[str]:
    return without_standard_error([sys.executable, "-c", _ASK_THE_RULE.format(taken=taken)])


def test_a_diagnostic_stays_off_standard_output_when_the_descriptor_was_closed() -> None:
    finished = _child()

    assert finished.returncode == 0
    assert finished.stdout == "stream\n", "the diagnostic followed sys.stderr onto standard output"


def test_the_rule_answers_the_stream_even_when_something_else_holds_descriptor_2() -> None:
    # The rule used to decide both questions by asking ``os.fstat(2)``, which answers the *second*
    # one. The two coincide only while descriptor 2 is still free — and the rule runs after the
    # whole import graph has loaded, so anything that opened a file on the way took that number and
    # made the probe succeed with ``sys.stderr`` still unbuilt. The guard then skipped its own body
    # and every diagnostic went to standard output: the defect it exists to prevent, restored by the
    # thing meant to prevent it, and silently.
    finished = _child(taken=_SOMETHING_HOLDS_DESCRIPTOR_2)

    assert finished.returncode == 0, finished.stdout
    assert finished.stdout == "stream\n", (
        "descriptor 2 being held was read as standard error being present"
    )


def test_the_instrument_really_closes_the_descriptor() -> None:
    # The condition asserted rather than assumed. Everything above is a claim about a process that
    # has no standard error, and nothing that starts a process for you can produce one: every value
    # `subprocess` takes leaves the descriptor open on something.
    finished = without_standard_error(
        [sys.executable, "-c", "import os, sys; os.fstat(2)"],
    )

    assert finished.returncode != 0, "descriptor 2 was open — every reading here is of another run"


def test_text_already_written_stays_ahead_of_a_published_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # One stream, two layers, and each holds a buffer of its own: prose goes through the text layer,
    # and a published artefact goes to the byte layer beneath it because a document carries its own
    # encoding. Bytes written while text is still pending above them land FIRST, and the text is
    # pushed out after — measured, and it is the whole difference the emptying makes. So a run that
    # wrote anything to standard output before the document would put it *inside* what a parser has
    # to read, and a reader keeping the human report in a file would find its last sentence below
    # the document rather than above it. Nothing else can hold the order: the two buffers are not
    # ordered against each other.
    #
    # A real file rather than a capture fixture, whose stream is one object where this is about two
    # layers of one — and the whole bytes rather than a member test, since an order is exactly what
    # a membership assertion cannot see.
    destination = tmp_path / "report.json"
    stream = destination.open("w", encoding="utf-8")
    try:
        monkeypatch.setattr(sys, "stdout", stream)
        sys.stdout.write("the run's last sentence\n")

        hand_over_standard_output(b'{"schema_version": 2}\n')
    finally:
        monkeypatch.undo()
        stream.close()

    assert destination.read_bytes() == b'the run\'s last sentence\n{"schema_version": 2}\n', (
        "the document overtook text that was written before it"
    )
