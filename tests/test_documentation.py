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


# What separates a command line from the shell around it: the words the shell would hand to
# elenctic, up to the first thing it keeps for itself.
#
# This was a hand-written list of shell operators, and it was wrong three times in one afternoon —
# it learned `2>&-`, then `>&-`, each time because a document happened to use one. Measured against
# eleven ordinary constructs it still missed six, among them `&>out`, `|&`, `<<EOF` and a trailing
# `&`. A list of operators is a list of the ones somebody thought of, and there is no reading of it
# that says which are absent.
#
# So the operator set is not written here. `shlex` in punctuation mode isolates each one as its own
# token, from the shell's grammar rather than from anyone's recollection of it, and handles quoting
# on the way. One rule is still ours, and it is the shell's too: a redirection may carry the
# descriptor it applies to, written tight against the operator (`2>&1`). It is removed first, and
# the tightness is what makes that safe — `--budget 60 > out` keeps its `60`, because that one has
# a space after it and is an argument.
_FD_PREFIX = re.compile(r"(?<![\w-])\d+(?=[<>])")
_SHELL_PUNCTUATION = frozenset("();<>|&")


def _argv_shown_by(line: str) -> list[str]:
    lexer = shlex.shlex(_FD_PREFIX.sub("", line), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    argv: list[str] = []
    for word in list(lexer)[1:]:
        if word and set(word) <= _SHELL_PUNCTUATION:
            break
        argv.append(word)
    return argv


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

    An inline one is read from ``elenctic`` onward rather than from the backtick, because a command
    line is often shown inside a longer one — ``pixi run elenctic …`` is how the contributor guide
    tells a reader to invoke it, and anchoring at the backtick read straight past it. That was not
    hypothetical: the one such line in these documents named no command and was refused, and this
    test said nothing about it.

    The word has to *start* where it is found, which is what keeps ``@elenctic solver clingcon``
    out. That is a contract tag a corpus author writes in a comment, and the only thing it shares
    with a command line is the eight letters in the middle of it.
    """
    prompted = [raw.removeprefix("$ ")] if raw.startswith("$ elenctic") else []
    return prompted + [
        span[found.start() :]
        for span in re.findall(r"`([^`]*)`", raw)
        if (found := re.search(r"(?<![\w@.-])elenctic ", span)) is not None
    ]


def test_no_command_line_shows_a_placeholder_the_shell_would_read_as_a_redirection() -> None:
    # `elenctic run <target> --format json` is not a command line a reader can copy. A shell reads
    # `<target>` as "take standard input from `target`" and then `>` takes the *next word* as a file
    # to write to — so the flags after it are consumed by the redirection rather than passed on.
    # `elenctic run <path>` is worse and easier to spot: it is a syntax error outright.
    #
    # Both shipped. The check beside this one could not see either, because it reads the command
    # line the *shell* would build, which is exactly the truncated one — the defect and the blind
    # spot have the same cause. So the rule is about the document instead: inside a command line, an
    # angle-bracket placeholder is never what the author meant, because the shell always has a
    # meaning for it. Write it in capitals.
    #
    # (`bash -n` was tried as the instrument and is not one: it rejects `<path>` and *accepts*
    # `<target> --format json`, which is valid shell doing the wrong thing. It would also put a
    # platform dependency in the gate for a class this rule already covers exactly.)
    shown = _command_lines()
    assert shown, "the pattern found no command line, which means it is no longer the pattern"
    placeholders = [
        (where, line, found) for where, line in shown if (found := re.findall(r"<[^<>]*>", line))
    ]
    assert not placeholders, (
        "shown to a reader, and read by a shell as a redirection rather than as a placeholder:\n"
        + "\n".join(f"  {where}: {line}\n      {found}" for where, line, found in placeholders)
        + "\n  Write a placeholder in capitals — TARGET, not <target>."
    )


def test_the_shell_is_cut_away_from_a_command_line_and_the_arguments_are_not() -> None:
    # The extraction above is the instrument the two checks either side of it read through, so it
    # owes a table of its own. It replaced a hand-written list of shell operators that was widened
    # twice in one afternoon, each time because a document used a form nobody had listed; measured
    # afterwards against ordinary constructs, that list still missed six of eleven. Every row marked
    # below is one it got wrong, and they are here so that a future simplification back to a list
    # cannot pass.
    #
    # The last two rows are the ones that make this a check rather than an assertion in one
    # direction: an argument that merely looks like a descriptor must survive, and a wrong flag in
    # front of a redirection must still be reached.
    cases: tuple[tuple[str, list[str]], ...] = (
        ("elenctic run tests/", ["run", "tests/"]),
        ("elenctic run tests/ | tee ci.log", ["run", "tests/"]),
        ("elenctic run tests/ > ci.log 2>&1", ["run", "tests/"]),
        ("elenctic run tests/ --format json 2>/dev/null", ["run", "tests/", "--format", "json"]),
        ("elenctic run tests/ >&-", ["run", "tests/"]),
        ("elenctic run tests/ &>out", ["run", "tests/"]),  # missed by the old list
        ("elenctic run tests/ &>>out", ["run", "tests/"]),  # missed
        ("elenctic run tests/ <&0", ["run", "tests/"]),  # missed
        ("elenctic run tests/ |& less", ["run", "tests/"]),  # missed
        ("elenctic run tests/ &", ["run", "tests/"]),  # missed
        ("elenctic run tests/ <<EOF", ["run", "tests/"]),  # missed
        ("elenctic run tests/ <<<data", ["run", "tests/"]),  # missed
        ("elenctic run tests/krbook", ["run", "tests/krbook"]),
        # A number that is an argument, not a descriptor: the space is what tells them apart, and
        # dropping it would stop checking the flag it belongs to without failing anything.
        ("elenctic run tests/ --budget 60 > out", ["run", "tests/", "--budget", "60"]),
    )
    wrong = [(line, want, got) for line, want in cases if (got := _argv_shown_by(line)) != want]
    assert not wrong, "the shell was cut in the wrong place:\n" + "\n".join(
        f"  {line!r}\n      got  {got}\n      want {want}" for line, want, got in wrong
    )
    # And the direction a table of expected values cannot hold on its own: the parser is still
    # reached through it, so a command line that is wrong in front of a redirection still fails.
    assert _refused("elenctic run tests/ --nope > out") is not None, (
        "a flag elenctic does not have, shown before a redirection, must still be caught"
    )

    # The table above hands `_argv_shown_by` its input directly, which is not where that input comes
    # from — so on its own it says nothing about the thing that builds one. This is the
    # composition, for the form it exists to handle: a command line shown inside a longer one.
    # Writing the first row of the table as `pixi run elenctic …` is how this was noticed: fed
    # straight in it keeps the `pixi`, and the guard read as broken when the fixture was.
    embedded = _shown_in("run it with `pixi run elenctic run tests/krbook` from the root")
    assert embedded == ["elenctic run tests/krbook"], (
        f"a command line shown inside a longer one is read from the word onward: got {embedded}"
    )
    assert _argv_shown_by(embedded[0]) == ["run", "tests/krbook"]
    assert _shown_in("the program is called `elenctic`") == [], (
        "and the bare name carrying no arguments is not a command line"
    )


def _refused(line: str) -> str | None:
    """Why the parser will not take ``line``, or ``None`` when it takes it.

    ``--help`` leaves by raising too, with the status that says nothing went wrong, so the status
    is what separates a refusal from an answer rather than the leaving. Both streams are swallowed:
    what argparse writes is the diagnostic, and it is wanted in the failure message rather than in
    the middle of the run.
    """
    argv = _argv_shown_by(line)
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


def test_the_number_of_textbook_programs_the_contributor_guide_states_is_the_number_there_are() -> (
    None
):
    # The same decay as the count above, in the same document, and the one that was still unchecked:
    # vendoring another textbook program is not an edit to a document either. The guide states this
    # count twice — once as what the corpus is for trying things against, once as what `tests/`
    # vendors — so both are read, and a patch that adds a program is told about both.
    programs = [path for path in (_ROOT / "tests/krbook/encodings").iterdir() if path.is_dir()]
    assert len(programs) < len(_IN_WORDS), (
        f"{len(programs)} programs is past the end of the table this test spells numbers with"
    )
    stated = _IN_WORDS[len(programs)]
    adrift = [
        phrase
        for phrase in (f"runs {stated} programs", f"vendors {stated} programs")
        if phrase not in _CONTRIBUTING
    ]
    assert not adrift, (
        f"tests/krbook/encodings holds {len(programs)} programs, and the contributor guide does "
        f"not say so in {adrift}: {sorted(path.name for path in programs)}"
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
