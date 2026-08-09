"""The standard error a program is owed, and the two separate things being owed it means.

Every entry point asks this rule before it writes anything, so what it guarantees on return is what
five programs depend on. It is two guarantees, not one, and they fail independently:

- **``sys.stderr`` is a stream.** Where it is ``None`` — which is what this language leaves when the
  descriptor was closed at start-up — ``print(..., file=sys.stderr)`` writes to standard *output*,
  and a diagnostic lands in the middle of whatever the run was publishing.
- **Descriptor 2 is open.** A closed descriptor is the lowest free number, so it is the next one
  handed out; the copy of standard output that the machine-readable path takes on its way in would
  *become* descriptor 2, and the redirect would then point standard output at itself.

The tests here are a process each, because both conditions are properties of a process's descriptor
table and neither can be arranged inside a test runner that has replaced the streams with objects of
its own.
"""

import subprocess
import sys

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
