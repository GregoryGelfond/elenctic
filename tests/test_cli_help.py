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

from elenctic.cli import main
from support import cli_help_section, cli_help_sections, cli_help_text

# Where every option elenctic defines is filed, written out rather than read off the parser, so
# that adding a flag and forgetting to file it fails here instead of being carried along by
# whatever the parser reports about itself.
#
# The whole mapping and not a count of its headings. "More than one heading" is a weaker claim than
# the one being made: two groups can be given the same title, argparse prints it twice, the option
# that says who the report is written for ends up under a heading that does not say so — and a
# count of distinct headings is still two.
_HOMES = {
    "--explain": "instead of running the corpus",
    "--print-schema": "instead of running the corpus",
    "--format": "the report",
    "--strict": "the run",
    "--budget": "the run",
    "--deadline": "the run",
}


def _options_by_heading() -> dict[str, list[str]]:
    """Which options ``--help`` filed under each of its headings.

    An option is an indented line whose first word begins with a dash — structural, so the reading
    survives whatever terminal width the help happens to be wrapped to.
    """
    return {
        heading: [line.split()[0].rstrip(",") for line in lines if line[2:3].startswith("-")]
        for heading, lines in cli_help_sections().items()
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


def test_every_option_is_filed_under_a_heading_that_says_what_it_is_for() -> None:
    # Six options in one block leaves a reader to work out for themselves that two of them do
    # something other than run the corpus, one chooses who the report is written for, and three
    # bound or sharpen the run. The headings say it instead.
    filed = _options_by_heading()
    catch_all = filed.get("options", [])
    assert catch_all == ["-h"], (
        "the catch-all heading names nothing about what an option is for, so it is left to the one "
        f"option this program did not define; it holds {catch_all}"
    )
    homes = {option: heading for heading, options in filed.items() for option in options}
    assert {option: homes.get(option) for option in _HOMES} == _HOMES


def test_the_help_says_what_each_exit_status_means() -> None:
    # The numbers alone would be a list a reader still has to interpret. Which statuses are
    # documented is checked against the ladder that produces them, in test_exit_status.py.
    ladder = cli_help_section("exit status")
    glossed = [line.strip() for line in ladder if line.strip()[:1].isdigit()]
    assert len(glossed) >= 4, f"each status is worth a sentence, not just a number: {glossed}"
    assert all(len(line.split(maxsplit=1)) == 2 for line in glossed), f"bare numbers in {glossed}"


def test_the_help_says_what_a_command_line_that_cannot_be_run_does(help_text: str) -> None:
    # The refusals are the one behaviour a reader meets by getting something wrong, which is the
    # worst moment to have to find out elsewhere that nothing was written. Asserted below the
    # options rather than anywhere in the text, because one option's own help already says a bad
    # command line is refused — and a reader who never asked for that option never reads it.
    _, _, closing = help_text.rpartition("\n\n")
    assert "refused" in closing, f"the help closes with:\n{closing}"
    assert "standard output" in closing, "what a refusal leaves on the stream a consumer parses"
