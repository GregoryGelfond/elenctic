"""What the documents state about this package, checked against the package.

The README is what everyone arriving reads, the changelog is what everyone upgrading reads, and the
contributor guide is what everyone patching reads — and all three are enforced by nothing that runs,
so a sentence in any of them stays true only for as long as somebody remembers to move it. What is
held here is the part that is mechanically checkable: a claim naming a value, a name or a count the
package also holds — and, in one direction the other way, a claim the *package* makes that one of
these documents settles. The boundary is worth stating plainly: a green run here does not mean any
of them is right, only that it does not contradict the package about the few things it names in the
package's own terms.

All three are read from the source tree rather than from the installed package, which is where they
are and where an edit to them lands. None is shipped inside the wheel, and these tests are not
either.
"""

import contextlib
import importlib
import io
import itertools
import json
import re
import shlex
import tomllib
from pathlib import Path

import elenctic
from elenctic.cli import _build_parser
from elenctic.registry import THEORY_EXTRA_ADVICE
from elenctic.solvers import TIME_BUDGET
from support import cli_help_text

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_CHANGELOG = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
_CONTRIBUTING = (_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

# A dotted name under this package, written as code — `elenctic.outcome.ExitStatus` and the like.
# Anchored at `elenctic.` so that a backticked flag, path or scrap of ASP is not mistaken for one.
_DOTTED_NAME = re.compile(r"`(elenctic(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`")


def test_the_release_a_reader_is_told_to_pin_is_this_release() -> None:
    # The one line in the README that goes stale by the project doing nothing wrong: cutting a
    # release moves the version, and the example keeps naming whichever release was current when it
    # was written — which still reads as current, and is the version a reader will actually pin.
    # Asserted as a set, so a second example added later cannot go stale quietly either.
    pinned = set(re.findall(r'tag = "(v[^"]+)"', _README))
    assert pinned == {f"v{elenctic.__version__}"}, (
        "the README's pin example must name this release; the version is single-sourced from "
        "elenctic.__version__, and cutting a release moves both"
    )


def test_the_default_budget_the_readme_states_is_the_default_the_package_has() -> None:
    # Stated twice in the README — as the gloss on the flag, and as a value inside the one worked
    # machine-readable document — and held by nothing; these quote the constant where the help
    # interpolates it.
    assert f"(default {TIME_BUDGET:g}s)" in _README, "the flag's gloss names the shipped default"
    assert f'"budget": {TIME_BUDGET}' in _README, "and so does the worked document"


def test_the_help_states_the_default_budget_the_way_the_readme_does() -> None:
    # Interpolating the constant is not enough on its own, which is how these two came to disagree:
    # the default is a float, so its bare repr reads `30.0s` where the README says `30s`, and a
    # reader comparing the flag's gloss with the documentation found two different numbers.
    #
    # What is held is the *agreement*, read out of the README rather than written here a third
    # time: an expectation spelled with the same format string as the line under test would follow
    # it wherever it went.
    (gloss,) = re.findall(r"\(default [0-9][^)]*\)", _README)
    assert gloss in " ".join(cli_help_text("run").split()), (
        f"the README's gloss {gloss!r} is not how --help says it"
    )


def test_the_readme_does_not_keep_a_second_copy_of_the_exit_status_ladder() -> None:
    # The ladder has one home, `ExitStatus`, and `--help` is rendered from it. A copy here would be
    # a second thing to keep true, and it is exactly the copy that went stale: it is prose, so
    # nothing renders it and nothing checks it. What the README carries instead is a pointer.
    #
    # The document section is not a copy in this sense and is deliberately left alone: it states
    # the ladder as something a consumer computes *from the document*, which is a different claim
    # from what the process returns, and it is checked against the packaged description elsewhere.
    running = _README.split("## Running", 1)[1].split("### Machine-readable output", 1)[0]
    assert "elenctic --help" in running, "the invitation to read the canonical list"
    assert "3 an elenctic bug" not in running, "and not a second list beside it"


def test_every_name_the_documents_tell_a_reader_to_import_is_one_they_can() -> None:
    # A document naming a home sends a reader to it. When the name moves, the sentence keeps its
    # confident shape and stops being true, and the reader who follows it meets an ImportError with
    # nothing to say about where the thing went. That is not hypothetical: the entry announcing the
    # exit-status type named it under the console entry, which is not where it lives.
    #
    # Every document at once, and asserted whole rather than one name at a time, so a reader of a
    # failure sees every name that has come adrift rather than the first.
    mentioned = sorted(
        {
            name
            for text in (_README, _CHANGELOG, _CONTRIBUTING)
            for name in _DOTTED_NAME.findall(text)
        }
    )
    assert mentioned, "the pattern found nothing at all, which means it is no longer the pattern"
    adrift = [name for name in mentioned if not _is_a_home(name)]
    assert not adrift, (
        f"named in one of the documents, and not where the name says it lives: {adrift}. A "
        f"document that names a home sends a reader there; these have moved, or never existed"
    )


def _is_a_home(dotted: str) -> bool:
    """Whether ``dotted`` names this thing *where it lives* — rather than somewhere it merely
    happens to be visible.

    Importability is too weak a question to ask, and the defect that prompted this is why: the entry
    announcing the exit-status type named it under the console entry, which imports it, so the name
    resolved and the sentence was still wrong. A reader following it would find the thing and learn
    the wrong home for it, and the day the console entry stops importing it the sentence breaks with
    no warning.

    Two homes count, because this package has two legitimate ones: the module a thing is defined in,
    and the curated top-level surface, which exists precisely so that a consumer need not know the
    first. Anything else is an incidental re-export.

    A thing carrying no ``__module__`` — a plain constant — cannot be placed this way, and is taken
    at its word rather than guessed about.
    """
    try:
        importlib.import_module(dotted)
    except ImportError:
        pass
    else:
        return True  # a module is its own home
    module, _, attribute = dotted.rpartition(".")
    try:
        parent = importlib.import_module(module)
    except ImportError:
        return False
    if not hasattr(parent, attribute):
        return False
    if module == elenctic.__name__:
        return attribute in elenctic.__all__
    return getattr(getattr(parent, attribute), "__module__", module) == module


def test_every_command_line_the_documents_show_is_one_elenctic_accepts() -> None:
    # A reader copies these. Nothing renders them and nothing has checked them, so they stay true
    # only while somebody remembers — and the record already holds the failure twice: five console
    # transcripts that are not what the tool prints, and a module count that went stale because
    # adding a module is not an edit to a document, so nobody was prompted. Changing the *grammar*
    # is the same shape one size up, and it reaches every line at once.
    #
    # Asserted whole rather than one line at a time, so a reader of a failure sees every line that
    # has come adrift rather than the first.
    shown = _command_lines()
    assert shown, "the pattern found no command line, which means it is no longer the pattern"
    refused = [(where, line, why) for where, line in shown if (why := _refused(line)) is not None]
    assert not refused, "shown to a reader, and refused by the parser:\n" + "\n".join(
        f"  {where}: {line}\n      {why}" for where, line, why in refused
    )


# What separates a command line from the shell around it. Cutting here rather than parsing the shell
# keeps the question this test asks — *would elenctic accept this?* — from becoming a second one
# about pipelines and redirections, which is nobody's grammar to check.
_SHELL_OPERATORS = frozenset({"|", ">", ">>", "<", "&&", ";"})


def _command_lines() -> list[tuple[str, str]]:
    """Every ``elenctic …`` command line the two documents of *instructions* show a reader.

    Two forms, because they use two: a transcript or usage line opening with a prompt, and a command
    written inline in prose. Both are things a reader copies.

    **The changelog is not among them, and the boundary is what the document is for.** These two
    tell a reader what to run, so every command line in them must be one that runs. A changelog
    records what changed — and when a command line is what changed, saying so means naming the
    spelling that stopped working, in prose, in a migration table, and in the alternation notation
    that describes a grammar. A rule requiring every quoted command line to parse forbids the
    changelog from doing its job, and three exemptions to keep it in are a rule that does not fit
    the document. It was checked here first, for one commit, and it did catch two entries written in
    a spelling that had gone stale; what is given up is catching the next such entry, and what it
    costs is that the changelog is swept by a person at the moment a grammar changes, which is when
    they are already sweeping.
    """
    return [
        (f"{name}:{number}", line)
        for name, text in (("README.md", _README), ("CONTRIBUTING.md", _CONTRIBUTING))
        for number, raw in enumerate(text.splitlines(), start=1)
        for line in _shown_in(raw)
    ]


def _shown_in(raw: str) -> list[str]:
    """The command lines one line of a document shows — none, one, or several.

    A prompt makes a command line whatever follows it, bare ``elenctic`` included. Backticks do not:
    they are also how these documents write the program's *name*, and a name takes no arguments —
    so an inline one counts as a command line only where it carries some.
    """
    prompted = [raw.removeprefix("$ ")] if raw.startswith("$ elenctic") else []
    return prompted + re.findall(r"`(elenctic [^`]*)`", raw)


def _refused(line: str) -> str | None:
    """Why the parser will not take ``line``, or ``None`` when it takes it.

    ``--help`` leaves by raising too, with the status that says nothing went wrong, so the status
    is what separates a refusal from an answer rather than the leaving. Both streams are swallowed:
    what argparse writes is the diagnostic, and it is wanted in the failure message rather than in
    the middle of the run.
    """
    words = shlex.split(line, comments=True)
    argv = list(itertools.takewhile(lambda word: word not in _SHELL_OPERATORS, words[1:]))
    said, printed = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stderr(said), contextlib.redirect_stdout(printed):
            _build_parser().parse_args(argv)
    except SystemExit as leaving:
        if leaving.code:
            return said.getvalue().strip().splitlines()[-1]
    return None


def test_the_readmes_library_example_runs_and_does_what_it_says(tmp_path: Path) -> None:
    """The worked example a consumer copies, run as written rather than read.

    This is the one block in either document that a reader will paste into their own project, and
    the release it demonstrates is the one this branch exists for — so "does it still import" is
    not the question. It is extracted from the README itself, so an edit to the prose is what runs.

    Run as a process, in a directory laid out the way the example assumes, because the example ends
    by leaving with a status and writes a file beside itself. Both are part of what it claims.
    """
    import subprocess
    import sys

    # Bounded by the next top-level heading rather than by a named one. It was named, and the
    # section it named later moved *above* this one — so the split stopped cutting anything and
    # the slice ran to the end of the file. It kept passing because exactly one Python block
    # happened to follow, which is an instrument that has silently stopped measuring.
    after = _README.split("## Using elenctic as a library", 1)[1]
    assert "\n## " in after, "the library section is last, so nothing bounds the slice below"
    section = after.split("\n## ", 1)[0]
    block = re.search(r"```python\n(.*?)```", section, re.S)
    assert block is not None, "the library section no longer holds a Python block to check"

    (tmp_path / "encodings").mkdir()
    (tmp_path / "encodings" / "case.lp").write_text(
        "% @elenctic solver clingo\n% @expect sat\n% @model { a }\na.\n#show a/0.\n",
        encoding="utf-8",
    )
    (tmp_path / "example.py").write_text(block.group(1), encoding="utf-8")

    done = subprocess.run(
        [sys.executable, "example.py"], cwd=tmp_path, capture_output=True, text=True
    )

    assert done.returncode == 0, f"the example did not leave cleanly: {done.stderr}"
    assert done.stderr == "", (
        "the section this example sits under opens by saying the library is silent, so anything "
        "the library wrote on its own would contradict the prose it is there to demonstrate"
    )
    assert done.stdout == "running case.lp\n  pass\n", (
        "the observer is what prints, and it prints as the run goes — a case announced when it is "
        "taken up and again when it is judged"
    )
    document = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert document["summary"]["passed"] == 1, "and the document it wrote reports the run"


def test_the_changelog_has_a_dated_section_for_the_version_being_shipped() -> None:
    """The link a release cut is most likely to break, and the one nothing was watching.

    Bumping ``__version__`` and forgetting to rename ``[Unreleased]`` ships a package whose
    changelog has no section for it — silently, because every other check here compares the version
    against the README rather than against the changelog. Cutting a release is exactly when a
    document goes stale, so the cut is what this holds.
    """
    dated = re.search(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", _CHANGELOG, re.M)
    assert dated is not None, "no dated release section at all"
    assert dated.group(1) == elenctic.__version__, (
        f"the newest dated section is {dated.group(1)} and this is {elenctic.__version__}; a "
        f"release whose changelog does not describe it tells an upgrader nothing"
    )
    assert f"\n[{elenctic.__version__}]: " in _CHANGELOG, (
        "and the link definition at the foot has to resolve, or the heading is a dead link"
    )


def test_the_install_a_diagnostic_advises_is_the_one_the_readme_shows() -> None:
    # The one claim here that runs from the package to the document rather than the other way. The
    # README states, and it is true, that elenctic is not published to PyPI — which makes a bare
    # `pip install "elenctic[theory]"` a command that resolves nothing, and it is the likeliest
    # exit-2 a real user meets, so it is the worst place in the package for advice that cannot work.
    #
    # What is held is the *agreement*, and the working form is read out of the README rather than
    # written a second time here: spelled out, this test would be satisfied by any command that
    # merely looked plausible, including the next one somebody invents.
    assert "not published to PyPI" in _README, "the premise, stated where a reader meets it"
    (shown,) = re.findall(r'pip install "elenctic\[theory\][^"]*"', _README)
    assert shown in THEORY_EXTRA_ADVICE, (
        f"a diagnostic advises {THEORY_EXTRA_ADVICE!r}, and the README installs it with {shown!r}"
    )


# Numbers are written as words in these documents, so a check on one has to spell it the way the
# sentence does. The table stops where the package plausibly stops; a count past its end fails with
# the reason rather than reading as agreement, because an index error here would look like a bug in
# the test rather than a package that has outgrown it. Pinned against the formatter, which would
# otherwise give each word a line of its own and turn a table anyone can count into twenty-one.
_IN_WORDS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
    "nineteen", "twenty",
)  # fmt: skip


def test_the_number_of_modules_the_contributor_guide_states_is_the_number_there_are() -> None:
    # Orientation, and the one sentence in that guide that goes stale by the project doing nothing
    # wrong: adding a module is not an edit to a document, so nobody is prompted. It had already
    # happened — the guide said sixteen from the release that shipped, and `streams.py` made it
    # seventeen with nothing to say so. The count is worth keeping (a reader wants the scale before
    # they open anything), so it is checked instead of dropped.
    #
    # `__init__.py` is excluded because the sentence excludes it in its own next clause.
    modules = [path for path in (_ROOT / "src/elenctic").glob("*.py") if path.name != "__init__.py"]
    assert len(modules) < len(_IN_WORDS), (
        f"{len(modules)} modules is past the end of the table this test spells numbers with"
    )
    stated = _IN_WORDS[len(modules)]
    assert f"holds {stated} modules" in _CONTRIBUTING, (
        f"src/elenctic/ holds {len(modules)} modules, and the contributor guide does not say "
        f"{stated}: {sorted(path.name for path in modules)}"
    )


def test_every_module_allowed_to_print_is_one_that_does() -> None:
    # The other direction from the one ruff enforces. A module that prints without a waiver fails
    # the gate loudly; a waiver that outlives the print it was written for fails nothing, and the
    # next reader takes the list as a statement of which modules are meant to write to a terminal.
    # It nearly happened here: `streams.py` was on the list for one edit before it printed anything.
    ignores = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    waived = [
        path
        for path, rules in ignores["tool"]["ruff"]["lint"]["per-file-ignores"].items()
        if "T201" in rules
    ]
    assert waived, "the waiver key moved, and this test is no longer reading the list it names"
    silent = [path for path in waived if "print(" not in (_ROOT / path).read_text(encoding="utf-8")]
    assert not silent, (
        f"waived from T20 and printing nothing: {silent}. The list is read as the modules meant to "
        f"write to a terminal, so an entry that no longer does is a sentence about the wrong set"
    )
