"""What ``--help`` tells a reader, and that it is checked rather than merely written.

``--help`` is the only documentation a reader has once elenctic is installed, and it is prose in a
published artefact: nothing about it is enforced by the code it describes, so it can come to say
whatever an edit leaves behind. Two things are held here. Every option this program defines is filed
under a heading saying what it is for, rather than in one undifferentiated block that leaves a
reader to sort an action from a dial. And the statuses the help documents are the statuses the
ladder actually produces — asserted against ``exit_status`` itself, in ``test_exit_status.py``,
because a second list written beside a function is a second thing to keep true.

``main`` is called rather than a process spawned: ``--help`` is answered inside ``parse_args`` and
leaves from there, so it never reaches the region where standard output is a descriptor rather than
a stream, which is the reason the machine-readable tests need a child.
"""

import pytest

from elenctic.cli import _Command, main
from elenctic.outcome import ExitStatus
from support import cli_help_section, cli_help_sections, cli_help_text

# Where every option elenctic defines is filed, written out rather than read off the parser, so
# that adding a flag and forgetting to file it fails here instead of being carried along by
# whatever the parser reports about itself.
#
# Keyed by command, because a command is its own help screen: a dial belongs to the command that
# reads it, and asking one screen about another's option is asking the wrong parser. The command
# with no dials at all is here too, with nothing filed, so that giving it one is a change to this
# table rather than a change nothing notices.
#
# The whole mapping and not a count of its headings. "More than one heading" is a weaker claim than
# the one being made: two groups can be given the same title, argparse prints it twice, the option
# that says who the report is written for ends up under a heading that does not say so — and a
# count of distinct headings is still two.
_HOMES = {
    "run": {
        "--format": "the report",
        "--strict": "the run",
        "--budget": "the run",
        "--deadline": "the run",
    },
    "explain": {"--strict": "the run"},
    "schema": {},
}


def _options_by_heading(*command: str) -> dict[str, list[str]]:
    """Which options ``--help`` filed under each of its headings.

    An option is an indented line whose first word begins with a dash — structural, so the reading
    survives whatever terminal width the help happens to be wrapped to.
    """
    return {
        heading: [line.split()[0].rstrip(",") for line in lines if line[2:3].startswith("-")]
        for heading, lines in cli_help_sections(*command).items()
    }


@pytest.fixture
def help_text() -> str:
    return cli_help_text()


def test_asking_for_the_help_is_not_a_diagnostic(capsys: pytest.CaptureFixture[str]) -> None:
    # The help is what was asked for, so it belongs on the stream a reader redirects to keep, and
    # the run leaves saying nothing went wrong. Both are what `cli_help_text` relies on.
    with pytest.raises(SystemExit) as leaving:
        main(["--help"])
    captured = capsys.readouterr()
    assert leaving.value.code == 0
    assert captured.err == ""
    assert captured.out.startswith("usage: elenctic")


@pytest.mark.parametrize("command", sorted(_HOMES))
def test_every_option_is_filed_under_a_heading_that_says_what_it_is_for(command: str) -> None:
    # Options in one undifferentiated block leave a reader to sort them: which chooses who the
    # report is written for, and which bound or sharpen the run. The headings say it instead. Two
    # of the options this once covered are commands now and have no heading to be under, which is
    # the same sentence one level up — a reader no longer sorts an action out of a block of dials.
    filed = _options_by_heading(command)
    catch_all = filed.get("options", [])
    assert catch_all == ["-h"], (
        "the catch-all heading names nothing about what an option is for, so it is left to the one "
        f"option this program did not define; under {command} it holds {catch_all}"
    )
    homes = {option: heading for heading, options in filed.items() for option in options}
    assert {option: homes.get(option) for option in _HOMES[command]} == _HOMES[command]
    filed_here = {option for options in filed.values() for option in options} - {"-h"}
    assert filed_here == set(_HOMES[command]), (
        f"{command} offers {sorted(filed_here)}, and this table names {sorted(_HOMES[command])}. A "
        f"dial belongs to the command that reads it, and one nothing reads is worse than none"
    )


def test_the_commands_the_help_offers_are_the_commands_the_program_has() -> None:
    # The one thing `_Command`'s docstring claims cannot drift — the word a reader types and the
    # case the code dispatches on — asserted rather than claimed. Read off the help rather than off
    # the parser, because the help is what a reader has, and a command the parser takes and the help
    # never mentions is a command nobody can find.
    # A command is a line indented under the choices line argparse writes above them, which is at a
    # shallower indent and is not one — structural, so the reading survives whatever width the help
    # is wrapped to, and does not read `{run,explain,schema}` as a command called that.
    offered = cli_help_section("commands")
    listed = {line.split()[0] for line in offered if line.startswith("    ") and line[4].isalpha()}

    assert listed == {command.value for command in _Command}, (
        f"the help offers {sorted(listed)}; the program has {sorted(c.value for c in _Command)}"
    )
    assert listed == set(_HOMES), "and this file's table names the same ones"


# What each rung's gloss must actually tell a reader. Stated here rather than derived, because it
# is the *meaning* of the number and not anything the number computes — the same reason the
# conclusion glosses are written out. Without it the ladder can be rendered from the type, satisfy
# every structural check, and still say nothing: collapsing `USER_FAULT`'s sentence to "a fault you
# can fix" passed the whole suite, and `--help` is the only place a script author reads this.
_GLOSSED: dict[int, tuple[str, ...]] = {
    0: ("nothing went wrong",),
    1: ("decided wrong", "could not be decided"),
    2: (
        "bad contract",
        "corpus",
        "environment",
        "will not ground",
        "memory",
        "deadline",
        "hygiene",
    ),
    3: ("elenctic itself", "outranks"),
}


def test_the_help_says_what_each_exit_status_means() -> None:
    # The numbers alone would be a list a reader still has to interpret. Which statuses are
    # documented is checked against the ladder that produces them, in test_exit_status.py.
    ladder = cli_help_section("exit status")
    glossed = [line.strip() for line in ladder if line.strip()[:1].isdigit()]
    assert len(glossed) >= 4, f"each status is worth a sentence, not just a number: {glossed}"
    assert all(len(line.split(maxsplit=1)) == 2 for line in glossed), f"bare numbers in {glossed}"


@pytest.mark.parametrize("status", list(ExitStatus))
def test_the_gloss_of_a_status_says_what_lands_a_reader_there(status: ExitStatus) -> None:
    # Rendering from the type keeps a gloss from landing on the wrong rung; it does not keep one
    # from going empty on the right rung. `2` is the rung this matters most for, because it is the
    # one a reader meets for seven different reasons and the only place they are enumerated.
    for expected in _GLOSSED[status.value]:
        assert expected in status.gloss, (
            f"exit {status.value} is reached by something the help does not mention: {expected!r}"
        )


def test_the_help_says_what_a_command_line_that_cannot_be_run_does(help_text: str) -> None:
    # The refusals are the one behaviour a reader meets by getting something wrong, which is the
    # worst moment to have to find out elsewhere that nothing was written. Asserted below the
    # options rather than anywhere in the text, because one option's own help already says a bad
    # command line is refused — and a reader who never asked for that option never reads it.
    _, _, closing = help_text.rpartition("\n\n")
    assert "refused" in closing, f"the help closes with:\n{closing}"
    assert "standard output" in closing, "what a refusal leaves on the stream a consumer parses"
