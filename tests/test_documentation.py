"""What the shipped documents state about this package, checked against the package.

The landing page is what everyone arriving reads, the guides are what a user returns to, the
changelog is what everyone upgrading reads, and the contributor guide is what everyone patching
reads — and every one of them is enforced by nothing that runs, so a sentence in any of them stays
true only for as long as somebody remembers to move it. What is held here is the part that is
mechanically checkable: a claim naming a value, a name or a count the package also holds — and, in
one direction the other way, a claim the *package* makes that one of these documents settles. The
boundary is worth stating plainly: a green run here does not mean any of them is right, only that
it does not contradict the package about the few things it names in the package's own terms.

**A claim is looked for across the documents rather than in a named file.** Which page holds a given
sentence is an editorial decision that changes; whether the package still agrees with it is not. A
check keyed to a file name stops checking anything the day the section moves, and stops silently,
which is the failure this module exists to prevent — so each of these asserts it *found* its
subject before it judges it.

All are read from the source tree rather than from the installed package, which is where they are
and where an edit to them lands. None is shipped inside the wheel, and these tests are not either.
"""

import ast
import contextlib
import dataclasses
import importlib
import io
import json
import pkgutil
import re
import shlex
import subprocess
import symtable
import tokenize
import tomllib
from pathlib import Path
from urllib.parse import unquote

import elenctic

# `_Command` and `_parse` are past `cli.__all__`, which offers `main` alone. The sweeps below are
# derived from the command enumeration rather than written three times, and `_parse` settles a
# command line without running it — which is what lets a documented invocation be checked here.
from elenctic.cli import _Command, _parse
from elenctic.expectation import KNOWN_TAGS, ContractError, has_contract, parse_contract
from elenctic.json_report import SCHEMA_VERSION
from elenctic.outcome import ErrorKind, RunOutcome
from elenctic.registry import THEORY_EXTRA_ADVICE
from elenctic.solvers import MODEL_CAP, TIME_BUDGET
from support import cli_help_text

_ROOT = Path(__file__).resolve().parent.parent
_README = (_ROOT / "README.md").read_text(encoding="utf-8")
_CHANGELOG = (_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
_CONTRIBUTING = (_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")


def _documents_of_instruction() -> dict[str, str]:
    """Every document that tells a reader how to use elenctic, keyed by the path a failure names.

    **Derived, not listed** — every Markdown document this repository ships, save the one exception
    below. A page is swept because of what it *is*, rather than because somebody remembered to add
    it to a tuple here.

    Written first as *the landing page, the contributor guide, and everything under* ``docs/``,
    which is a list of three wearing a derivation's clothes: it silently omitted ``SECURITY.md``,
    which is a document of instruction by every test that matters — a reader follows it, and it
    shows a command line they copy. The rule is what the repository ships to a reader, and the only
    reason to know a file's name is to exclude it.

    ``CHANGELOG.md`` is that one exclusion, on the boundary these checks already draw: a changelog
    records what changed, and when a command line or a contract is what changed, saying so means
    naming the spelling that *stopped* working. A rule requiring every such line to still work
    forbids the document from doing its job. It is named here, once, where a reader can see the
    exception is deliberate rather than an omission — which is exactly what the first version of
    this could not show about ``SECURITY.md``.

    **Asked of git, because git is the authority on what this repository ships.** The second version
    globbed the root and ``docs/``, which is the same list of names one glob shorter: it reached
    eight of the nine Markdown files under version control and silently missed the pull-request
    template, which tells a contributor what to do and is read more often than most of ``docs/``.
    Any filesystem walk wide enough to find it also finds the caches and the environment, and
    excluding those means maintaining a list of the tools that happen to be installed — whereas
    ``.gitignore`` is that list, already written, and ``git ls-files`` is how to read it.
    """
    listed = subprocess.run(
        ["git", "-C", str(_ROOT), "ls-files", "-z", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    shipped = sorted(_ROOT / name for name in listed.split("\0") if name)
    # A sweep over nothing passes every check it feeds, so the empty case is a failure rather than a
    # quiet success: outside a checkout this module cannot answer the question it exists to ask.
    assert shipped, (
        "git listed no Markdown; this is not a checkout, and every sweep below is vacuous"
    )
    return {
        str(path.relative_to(_ROOT)): path.read_text(encoding="utf-8")
        for path in shipped
        if path.name != "CHANGELOG.md"
    }


_INSTRUCTIONS = _documents_of_instruction()

# The documents of instruction as one text, for a claim that may live in any of them and must live
# in one. Joined with a blank line so nothing reads across a boundary that is not a paragraph break.
_INSTRUCTED = "\n\n".join(_INSTRUCTIONS.values())

# The same text with every run of whitespace collapsed to one space. A claim written in prose is
# wrapped, and where the wrap falls is an editorial accident — so a check looking for a *phrase*
# looks here, and one looking for a line or a table row looks above. Without this, reflowing a
# paragraph could split a sentence a check matches on, and the check would report the claim missing
# when a reader can see it perfectly well.
_INSTRUCTED_FLAT = " ".join(_INSTRUCTED.split())

# A dotted name under this package, written as code — `elenctic.outcome.ExitStatus` and the like.
# Anchored at `elenctic.` so that a backticked flag, path or scrap of ASP is not mistaken for one.
_DOTTED_NAME = re.compile(r"`(elenctic(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`")


def test_the_release_a_reader_is_told_to_pin_is_this_release() -> None:
    # The one line in the documents that goes stale by the project doing nothing wrong: cutting a
    # release moves the version, and the example keeps naming whichever release was current when it
    # was written — which still reads as current, and is the version a reader will actually pin.
    # Asserted as a set, so a second example added later cannot go stale quietly either.
    pinned = set(re.findall(r'tag = "(v[^"]+)"', _INSTRUCTED))
    assert pinned == {f"v{elenctic.__version__}"}, (
        "the pin example must name this release; the version is single-sourced from "
        "elenctic.__version__, and cutting a release moves both"
    )


def test_the_badges_claim_what_the_package_declares() -> None:
    # A badge is a claim, and it is the loudest one on the page: it is the first thing a visitor
    # reads and the last thing anyone edits. Three of these are claims about values that live in
    # `pyproject.toml` — the licence, the version floor, and which workflow reports the build — and
    # a badge is an image, so a drifted one goes on rendering confidently in the wrong colour.
    #
    # The fourth is different in kind and is checked differently: `ruff` claims a practice rather
    # than a value, so what holds it is that the practice is configured. A project that stopped
    # using ruff would keep the badge, because nothing about deleting a lint configuration prompts
    # anyone to look at an image at the top of a document.
    manifest = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    badges = dict(re.findall(r"^\[!\[([^\]]+)\]\(([^)]+)\)\]", _README, re.M))
    licence = manifest["project"]["license"]
    # Each is looked up by the alt text a reader would see, and each is asserted present before it
    # is judged: a badge that was removed and one that disagrees are different news, and a bare
    # lookup would report the first as the second — or as a KeyError, which is neither.
    wanted = ["CI", "Ruff", "Python", f"License: {licence}"]
    missing = [name for name in wanted if name not in badges]
    assert not missing, f"the badge row no longer carries {missing}; it carries {sorted(badges)}"

    # The build badge names the workflow it reports on, and a renamed workflow renders as a
    # permanently unknown build rather than as an error anyone is told about.
    workflow = re.search(r"/actions/workflows/([^/]+)/badge\.svg", badges["CI"])
    assert workflow is not None, "the CI badge no longer names a workflow"
    assert (_ROOT / ".github/workflows" / workflow.group(1)).is_file(), (
        f"the CI badge reports on {workflow.group(1)}, and there is no such workflow"
    )

    # The floor, read out of the badge the way a reader sees it rather than out of its escaping.
    shown = unquote(badges["Python"])
    floor = manifest["project"]["requires-python"].lstrip(">=")
    required = manifest["project"]["requires-python"]
    assert f"≥ {floor}" in shown, (
        f"the Python badge shows {shown!r} and the package requires {required!r}"
    )

    assert f"License-{licence}-" in badges[f"License: {licence}"], (
        f"the licence badge does not show {licence!r}: {badges[f'License: {licence}']}"
    )
    assert "ruff" in manifest["tool"], "the badge claims ruff and the project does not configure it"


def test_every_place_that_says_where_elenctic_comes_from_says_the_same_thing() -> None:
    """Where elenctic is installed from is one fact, and this package states it in five places.

    Four are instructions a reader follows and the fifth is a diagnostic elenctic prints at someone
    who is already stuck, so a disagreement is met by the reader least able to work around it. Only
    one pairing was held — the theory-install line against the constant — which is the pairing that
    caught the advice naming an install that resolved nothing. The others were free to drift: a
    fenced TOML block is read by nothing here, since the command-line check reads only lines opening
    with ``elenctic`` and the contract check only ``asp`` blocks.

    That matters on one particular day. Publishing to an index is a change to *every* one of these,
    and the ones nothing holds are the ones that would be left behind — leaving the recommended
    install pointing at a git URL for a package that no longer needs it.

    So the fact is derived at each site and the sites are required to agree, rather than each being
    compared against a spelling written here. What the correct answer *is* stays outside this check,
    which is what lets it go on holding after the answer changes.
    """
    from_git: dict[str, bool] = {}

    # The premise, stated in prose. Absent, the reader is being told elenctic comes from an index.
    from_git["the prose"] = "not published to PyPI" in _INSTRUCTED_FLAT

    # The pixi block, which is the *recommended* install and the one furthest from any check.
    pixi = re.search(r"^elenctic = (.+)$", _INSTRUCTED, re.M)
    assert pixi is not None, "no document shows a pixi dependency entry for elenctic any more"
    from_git["the pixi entry"] = "git" in pixi.group(1)

    # Every `pip install …` line naming elenctic, of which there are two: the answer-set fragment
    # and the theory extra. Asserted non-empty, because a check that found none would pass.
    installs = re.findall(r"pip install \"?([^\"\n]*elenctic[^\"\n]*)\"?", _INSTRUCTED)
    assert installs, "no document shows a pip install for elenctic any more"
    for shown in installs:
        from_git[f"pip install {shown.strip()}"] = "git+" in shown

    # And the sentence elenctic itself prints when the theory backend is missing.
    from_git["THEORY_EXTRA_ADVICE"] = "git+" in THEORY_EXTRA_ADVICE

    answers = set(from_git.values())
    assert len(answers) == 1, (
        "these disagree about where elenctic is installed from, so following one and reading "
        "another leaves a reader with an install that cannot work:\n"
        + "\n".join(
            f"  {'from git ' if git else 'from index'}  {site}"
            for site, git in sorted(from_git.items(), key=lambda pair: (pair[1], pair[0]))
        )
    )


def test_the_version_the_citation_file_states_is_this_release() -> None:
    # A citation file names a version, and a version in a file nothing reads is a version nobody
    # updates — so this joins the pin example as a thing the release cut has to move, and as a thing
    # that says so when it is forgotten. A citation naming a release that was never cut is worse
    # than one naming none: it sends a reader looking for an artefact that does not exist.
    #
    # Read with a pattern rather than a YAML parser, deliberately. The file is YAML, and parsing it
    # would need a dependency this project does not otherwise have; what is being checked is one
    # scalar on one line, and a pattern that fails to find it fails loudly below.
    citation = (_ROOT / "CITATION.cff").read_text(encoding="utf-8")
    stated = re.search(r"^version: (.+)$", citation, re.M)
    assert stated is not None, "CITATION.cff no longer states a version in the shape this reads"
    assert stated.group(1).strip().strip('"') == elenctic.__version__, (
        f"CITATION.cff cites {stated.group(1).strip()} and this is {elenctic.__version__}"
    )


def test_every_link_between_the_documents_goes_somewhere() -> None:
    # A `docs/` tree means relative links, and a relative link is the one thing in a document that
    # is both certain to be written and certain to rot: moving a page is an edit to every document
    # that points at it, and nothing about moving a file prompts that edit.
    #
    # Resolved against the directory of the document holding the link, which is what a reader's
    # renderer does. Anchors are checked as far as the file — whether a heading exists is a question
    # about how a renderer slugs one, and that answer differs between renderers.
    # **Both notations markdown has**, because a link written the other way is still a link a
    # reader follows, and converting a table to the reference form is an ordinary tidying edit —
    # one that would otherwise lift those links out of this check without removing them from the
    # page. Inline first, then the definitions a reference link resolves through.
    linked = [
        (name, target)
        for name, text in _INSTRUCTIONS.items()
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text)
        + re.findall(r"^\[[^\]]+\]:\s*(\S+)", text, re.M)
    ]
    # And the found-guard every other sweep here has, for the case where there is nothing left to
    # read at all: a check that reports a clean result about an empty set has stopped measuring.
    assert linked, "no document holds a link any more, which means this is no longer reading them"
    broken = [
        f"{name} -> {target}"
        for name, target in linked
        if not target.startswith(("http://", "https://", "mailto:", "#"))
        and not (_ROOT / name).parent.joinpath(target.split("#", 1)[0]).exists()
    ]
    assert not broken, "a link in a document points at nothing:\n  " + "\n  ".join(broken)


def test_the_default_budget_the_documents_state_is_the_default_the_package_has() -> None:
    # Stated twice — as the gloss on the flag, and as a value inside the one worked
    # machine-readable document — and held by nothing; these quote the constant where the help
    # interpolates it.
    assert f"(default {TIME_BUDGET:g}s)" in _INSTRUCTED_FLAT, "the flag's gloss names the default"
    assert f'"budget": {TIME_BUDGET}' in _INSTRUCTED_FLAT, "and so does the worked document"


def test_the_help_states_the_default_budget_the_way_the_documents_do() -> None:
    # Interpolating the constant is not enough on its own, which is how these two came to disagree:
    # the default is a float, so its bare repr reads `30.0s` where the documents say `30s`, and a
    # reader comparing the flag's gloss with the documentation found two different numbers.
    #
    # What is held is the *agreement*, read out of the documents rather than written here a third
    # time: an expectation spelled with the same format string as the line under test would follow
    # it wherever it went.
    (gloss,) = re.findall(r"\(default [0-9][^)]*\)", _INSTRUCTED_FLAT)
    assert gloss in " ".join(cli_help_text("run").split()), (
        f"the documents' gloss {gloss!r} is not how --help says it"
    )


def test_the_model_cap_the_documents_state_is_the_one_the_package_enforces() -> None:
    # The bound has no flag, so a document is the only way anyone learns it — which makes the
    # sentence the whole of what a user is promised, and made it the one published number nothing
    # compared against the package. Its sibling `TIME_BUDGET` has been checked since it was written.
    #
    # Read as the words the sentence uses rather than as digits: a bound of this size is written
    # "a million" by anyone describing it, and a check keyed on `1000000` would pass a document that
    # had stopped saying anything a reader could act on.
    stated = re.search(r"holds at most (a million|[\d,]+) answer sets", _INSTRUCTED_FLAT)
    assert stated is not None, (
        "no document states the enumeration bound any more, and it has no flag — so nothing tells "
        "a reader why an honest @count comes back UNDECIDED"
    )
    spelled = {"a million": 1_000_000}.get(stated.group(1), 0) or int(
        stated.group(1).replace(",", "")
    )
    assert spelled == MODEL_CAP, (
        f"the documents say a solve holds at most {stated.group(1)} answer sets, and the package "
        f"stops at {MODEL_CAP:,}"
    )


def test_no_document_keeps_a_second_copy_of_the_exit_status_ladder() -> None:
    # The ladder has one home, `ExitStatus`, and `--help` is rendered from it. A copy in prose is a
    # second thing to keep true, and it is exactly the copy that went stale: nothing renders it and
    # nothing checks it. What the documents carry instead is a pointer, and the pointer is asserted
    # too — dropping it would leave a reader with no canonical list at all, which the negative half
    # of this check cannot see.
    #
    # Stated over the whole set rather than over a slice of one file. It used to bound itself by two
    # headings in one file, which meant it stopped checking anything the moment either moved; what
    # it forbids is a *copy*, and a copy is no more welcome on one page than another.
    #
    # The machine-readable page is not a copy in this sense and is deliberately untouched: it states
    # the ladder as something a consumer computes *from the document*, which is a different claim
    # from what the process returns, and it is checked against the packaged description elsewhere.
    # So the negative is keyed on the spelling the prose copy used, not on the numbers.
    assert "elenctic --help" in _INSTRUCTED_FLAT, "the invitation to read the canonical list"
    assert "3 an elenctic bug" not in _INSTRUCTED_FLAT, "and not a second list beside it"


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
            for text in (*_INSTRUCTIONS.values(), _CHANGELOG)
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
        for name, text in _INSTRUCTIONS.items()
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
    #
    # Both bracket forms, because both are how an author reaches for a placeholder and both are
    # shell syntax: `<x>` is a redirection, and `[x]` is a glob matching one of the characters
    # inside it — so `elenctic run [target]` runs against a file called `t`, `a`, `r`, `g` or `e`
    # if one is there, and against a directory literally named `[target]` if not. That one shipped,
    # and the check beside this could not see it either: `[target]` is a perfectly good word to a
    # lexer, so the parser accepts it as a target and nothing objects. The rule is about the
    # notation rather than about either character: a placeholder is written in capitals, which no
    # shell reads as anything.
    shown = _command_lines()
    assert shown, "the pattern found no command line, which means it is no longer the pattern"
    placeholders = [
        (where, line, found)
        for where, line in shown
        if (found := re.findall(r"<[^<>]*>|\[[^\[\]]*\]", line))
    ]
    assert not placeholders, (
        "shown to a reader, and read by a shell as a redirection rather than as a placeholder:\n"
        + "\n".join(f"  {where}: {line}\n      {found}" for where, line, found in placeholders)
        + "\n  Write a placeholder in capitals — TARGET, not <target> or [target]."
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
            _parse(argv)
    except SystemExit as leaving:
        if leaving.code:
            return said.getvalue().strip().splitlines()[-1]
    return None


def _asp_blocks() -> list[tuple[str, str]]:
    """Every fenced ``asp`` block the two documents of *instructions* show a reader.

    The same two documents :func:`_command_lines` reads, bounded for the same reason and not by
    analogy with it. A changelog has to be able to show the contract that *stopped* parsing, and it
    does: its single ``asp`` block carries a ``@cautious`` line and no ``@expect``, shown precisely
    because that shape is refused. A rule requiring every block to parse would forbid the changelog
    from recording what changed, which is rule 17 — three exemptions to keep a document inside a
    rule is the rule not fitting the document.
    """
    return [
        (name, block)
        for name, text in _INSTRUCTIONS.items()
        # The info string is read past rather than required to be bare: `asp` may one day carry a
        # title or a highlight range, and a fence retitled that way would silently leave this set
        # while the other blocks kept the assertion green.
        for block in re.findall(r"```asp[^\n]*\n(.*?)```", text, re.S)
    ]


def _tags_written_in(block: str) -> list[str]:
    """Every ``@word`` **elenctic's own comment reader** takes as a tag in this block, known or not.

    Read through the lexer rather than through a pattern of this test's own, because the question is
    what elenctic would treat as a tag position, and a second answer to that is a second thing to
    keep true. It is not the same answer: a tag trailing a rule — ``a.  % @expect sat`` — is one
    elenctic honours, and it is measurably not what a line-anchored pattern finds. So a *mistyped*
    trailing tag would have been invisible to the check that exists to catch mistyped tags.
    """
    # `_lex` and `_tag_comments` are past `expectation.__all__`, for the reason the docstring
    # above gives: the question is what elenctic's own reader takes as a tag position, and
    # `parse` answers a different one.
    from elenctic.expectation import _lex, _tag_comments

    return [tagged.tag for tagged in _tag_comments(_lex(block).comments)]


def test_every_contract_the_documents_show_is_one_elenctic_parses() -> None:
    # The sibling of the command-line check, over the other notation these documents quote. A reader
    # copies both, nothing renders either, and the contract grammar is the one this release changed
    # most — so an example written against a spelling that has moved reads as current and is not.
    #
    # Two directions, because one of them cannot see the failure that matters most. A block that
    # carries a contract must parse; and a block that *means* to carry one must be recognised as
    # carrying one, since a mistyped tag is not a known tag, so the file is silently a library — it
    # runs nothing, reports nothing, and the corpus still comes back green.
    blocks = _asp_blocks()
    assert blocks, "the pattern found no asp block, which means it is no longer the pattern"
    unknown = [
        (name, sorted(strange))
        for name, block in blocks
        if (strange := set(_tags_written_in(block)) - KNOWN_TAGS)
    ]
    assert not unknown, (
        "shown with an @-tag elenctic does not know, so the file it is copied into is silently a "
        "library — it runs nothing, reports nothing, and the corpus still comes back green:\n"
        + "\n".join(f"  {name}: {tags}" for name, tags in unknown)
    )
    refused = [
        (name, block, str(why))
        for name, block in blocks
        if has_contract(block) and (why := _unparsed(block)) is not None
    ]
    assert not refused, "shown to a reader, and refused by the parser:\n" + "\n".join(
        f"  {name}: {block.splitlines()[0]}\n      {why}" for name, block, why in refused
    )


def _unparsed(block: str) -> Exception | None:
    """Why elenctic will not read this block's contract, or ``None`` when it reads it."""
    try:
        parse_contract(block)
    except (ContractError, ValueError) as refusal:
        return refusal
    return None


def test_the_library_example_runs_and_does_what_it_says(tmp_path: Path) -> None:
    """The worked example a consumer copies, run as written rather than read.

    This is the one block in the documents that a reader will paste into their own project, and the
    release it demonstrates is the one this branch exists for — so "does it still import" is not the
    question. It is extracted from the document itself, so an edit to the prose is what runs.

    Run as a process, in a directory laid out the way the example assumes, because the example ends
    by leaving with a status and writes a file beside itself. Both are part of what it claims.

    **Found by being the only one, rather than by where it sits.** This used to slice a named
    heading out of one file, and slicing is what kept going wrong: it was bounded by a heading that
    later moved *above* it, so the split cut nothing and the slice ran to end of file — passing only
    because exactly one Python block happened to follow. Asking the whole document set for its
    Python blocks and requiring exactly one has no slice to be wrong about, and it fails loudly
    rather than vacuously if the example is moved, duplicated or dropped.
    """
    import subprocess
    import sys

    found = [
        (name, match.group(1))
        for name, text in _INSTRUCTIONS.items()
        for match in re.finditer(r"```python\n(.*?)```", text, re.S)
    ]
    assert len(found) == 1, (
        f"the documents should hold exactly one Python example, and this is what a consumer "
        f"copies; found {[name for name, _ in found]}"
    )
    (_where, example) = found[0]

    (tmp_path / "encodings").mkdir()
    (tmp_path / "encodings" / "case.lp").write_text(
        "% @elenctic solver clingo\n% @expect sat\n% @model { a }\na.\n#show a/0.\n",
        encoding="utf-8",
    )
    (tmp_path / "example.py").write_text(example, encoding="utf-8")

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


def _changelog_entries() -> list[tuple[str, int, str, str]]:
    """Every changelog entry as ``(release, line, headline, body)``.

    An entry runs from a bullet to the next bullet or heading, which is the shape every one of them
    has had since the first release. The headline is the bolded lead — the unit a reader actually
    scans, since nobody reads a changelog end to end; they look down the bold text for the thing
    that concerns them and read only that entry's body.

    **An entry is a bullet under a category**, and that is the definition rather than a detail: the
    breaking-changes index at the head of a release is a list of bullets too, and it is a set of
    pointers rather than a set of entries. Read as entries they would be counted twice and held to
    a rule about headlines they have no business having. The categories are what the format names,
    so a bullet above the first of them is preamble.
    """
    found: list[tuple[str, int, str, str]] = []
    release, gathered, opened, under_category = "", "", 0, False

    def close() -> None:
        if not gathered:
            return
        head = re.match(r"- \*\*(.+?)\*\*", gathered)
        found.append(
            (release, opened, head.group(1), gathered[head.end() :].strip())
            if head is not None
            else (release, opened, "", gathered)
        )

    # The sentinel closes the final entry without the loop needing a second exit.
    for number, line in enumerate([*_CHANGELOG.splitlines(), "## [end of file]"], start=1):
        if line.startswith(("- ", "### ", "## [")):
            close()
            gathered, opened = (
                (line, number) if line.startswith("- ") and under_category else ("", 0)
            )
            if line.startswith("### "):
                under_category = True
            elif line.startswith("## ["):
                release, under_category = line.split("]")[0].removeprefix("## ["), False
        elif gathered:
            gathered = f"{gathered} {line.strip()}"
    return found


def test_every_changelog_entry_opens_with_a_headline_a_reader_can_scan() -> None:
    # Nobody reads a changelog end to end. They run their eye down the bold text looking for the
    # thing that concerns them, and read one entry. That makes the bolded lead the load-bearing
    # part: an entry without one is invisible to the only way the document is used, however good
    # its prose is.
    entries = _changelog_entries()
    assert len(entries) > 20, (
        f"only {len(entries)} entries found, so this is no longer reading them"
    )
    bare = [f"{release} line {at}" for release, at, head, _ in entries if not head]
    assert not bare, (
        f"these entries open with no bolded headline, so a reader scanning for what concerns them "
        f"passes straight over: {bare}"
    )


def test_no_changelog_headline_has_grown_out_of_being_one() -> None:
    # The verbosity check, and it is a **ratchet rather than a derivation** — worth saying plainly,
    # because this project does not otherwise accept a number nobody can justify.
    #
    # Measured across every entry in every release before it was written: 83 entries, headline
    # length median 13 words, 90th percentile 17, longest 23. The cap is the observed longest plus
    # slack, so it holds a property the document already has and costs nothing to keep. What it
    # forbids is a headline that has stopped being one — a paragraph in bold that a reader cannot
    # scan — not the difference between thirteen words and seventeen.
    #
    # **The body is deliberately not capped**, and two candidate rules were measured and rejected
    # rather than merely not written. A word cap on bodies fails immediately: they run from 9 words
    # to 609, and the longest is a migration table that earns every line. "A long entry must carry
    # a fence or a table" fails too — eleven entries of 180 words or more carry neither, across
    # shipped releases, so it would need its exemptions on the day it was written. A rule needing
    # exemptions to fit the document is the rule not fitting the document.
    longest = 25
    entries = _changelog_entries()
    assert entries, "no entries found, so this is no longer reading them"
    overgrown = [
        (release, at, len(head.split()), head[:60])
        for release, at, head, _ in entries
        if len(head.split()) > longest
    ]
    assert not overgrown, (
        f"a headline is what a reader scans, and these have stopped being one (cap {longest} "
        f"words): {overgrown}"
    )


_BREAKS = "**What can break:**"


def test_the_breaking_changes_index_and_the_entries_it_indexes_agree() -> None:
    # An index is a second account of something, which is the shape this project spends its time
    # removing — so it is derived from the entries rather than kept beside them. What makes that
    # possible is that the document already had a convention for saying an entry asks something of
    # a reader; it was simply spelled five ways, and the minority spellings were the ones a reader
    # scanning for them would miss.
    #
    # The release being cut is the one an upgrader reads, so the index is the unreleased section's
    # alone. A shipped release's index is history and is not regenerated.
    entries = _changelog_entries()
    assert entries, "no entries found, so this is no longer reading them"
    breaking = [
        head.rstrip(".")
        for release, _at, head, body in entries
        if release == "Unreleased" and _BREAKS in f"{head} {body}"
    ]
    assert breaking, (
        f"no unreleased entry is marked {_BREAKS}, so either nothing breaks — in which case the "
        f"index should go — or the marker has been spelled some other way again"
    )
    # One index line per entry, unwrapped — which is a constraint on the index rather than an
    # assumption about it, and it is stated because a reader reflowing that list would otherwise
    # be surprised. Wrapped, a line stops matching and this fails naming it, which is the right
    # way round: the index is generated from the entries, so hand-editing it is the thing to be
    # told about.
    listed = re.findall(r"^- (.+)$", _unreleased_index(), re.M)
    assert sorted(listed) == sorted(breaking), (
        "the breaking-changes index and the entries marked "
        f"{_BREAKS} do not agree.\n  indexed but not marked: {sorted(set(listed) - set(breaking))}"
        f"\n  marked but not indexed: {sorted(set(breaking) - set(listed))}"
    )


def _unreleased_index() -> str:
    """The breaking-changes index at the head of the unreleased section — everything between that
    heading and the first category under it.

    Bounded by the first ``###`` rather than by a heading of its own, deliberately: Keep a Changelog
    names six categories and this is not one of them, so it is a lead paragraph rather than a
    seventh. A reader meets it before any category, which is where an upgrader looks.
    """
    after = _CHANGELOG.split("## [Unreleased]", 1)
    assert len(after) == 2, "the changelog no longer has an unreleased section"
    assert "\n### " in after[1], "the unreleased section has no categories under it"
    return after[1].split("\n### ", 1)[0]


def test_the_changelog_has_a_dated_section_for_the_version_being_shipped() -> None:
    """The link a release cut is most likely to break, and the one nothing was watching.

    Bumping ``__version__`` and forgetting to rename ``[Unreleased]`` ships a package whose
    changelog has no section for it — silently, because every other check here compares the version
    against the package rather than against the changelog. Cutting a release is exactly when a
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


def test_the_install_a_diagnostic_advises_is_the_one_the_documents_show() -> None:
    # The one claim here that runs from the package to the document rather than the other way. The
    # documents state, and it is true, that elenctic is not published to PyPI — which makes a bare
    # `pip install "elenctic[theory]"` a command that resolves nothing, and it is the likeliest
    # exit-2 a real user meets, so it is the worst place in the package for advice that cannot work.
    #
    # What is held is the *agreement*, and the working form is read out of the document rather than
    # written a second time here: spelled out, this test would be satisfied by any command that
    # merely looked plausible, including the next one somebody invents.
    assert "not published to PyPI" in _INSTRUCTED_FLAT, "the premise, where a reader meets it"
    (shown,) = re.findall(r'pip install "elenctic\[theory\][^"]*"', _INSTRUCTED_FLAT)
    assert shown in THEORY_EXTRA_ADVICE, (
        f"a diagnostic advises {THEORY_EXTRA_ADVICE!r}, and the documents install it with {shown!r}"
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


def test_every_locus_the_package_can_file_is_one_the_documents_name() -> None:
    # The same vocabulary is documented twice, and only one copy was held. The packaged schema
    # glosses every `kind` a run can publish, and `test_json_schema.py` holds it against `ErrorKind`
    # itself; the locus table is the copy a reader meets first, and nothing asked it. So it
    # was the one that went stale — `containment` was added to the package during this release and
    # the table kept its seven rows, while a corpus whose case reaches outside itself publishes
    # `"kind": "containment"` and prints `CONTAINMENT ERROR —`.
    #
    # Derived from `ErrorKind` rather than from a list here, which is the whole point: a locus added
    # later is a row this test asks for, and there is nowhere to add one without being asked.
    rows = set(re.findall(r"^\| `([a-z_]+)` \| ", _INSTRUCTED, re.M))
    members = {kind.value for kind in ErrorKind}
    assert not members - rows, (
        f"a run can file these loci and no locus table has a row for them: "
        f"{sorted(members - rows)}. A reader met by the diagnostic, and a consumer decoding "
        f"`kind`, both look the word up in that table"
    )
    assert not rows - members, (
        f"a locus table has rows for loci nothing can file: {sorted(rows - members)}"
    )
    # And the count the prose states beside it, which is the half a new row leaves behind: the
    # sentence about which loci a consumer can catch counts them, and it counted seven.
    assert f"of the {_IN_WORDS[len(members)]}" in _INSTRUCTED_FLAT, (
        f"there are {len(members)} loci, and the prose beside the table does not say "
        f"{_IN_WORDS[len(members)]}"
    )


def test_the_fields_the_documents_call_closed_are_the_ones_the_schema_closes() -> None:
    # The second instance of the class the locus table is the first of: a vocabulary written down
    # twice, once where a machine can be asked and once where only a reader goes. Here the prose is
    # the copy that is right and unheld — it names five closed enumerations and three open-valued
    # fields, and this is the sentence `schema_version` is *defined* by, so a field that quietly
    # gained or lost an `enum` would leave a consumer's upgrade policy resting on a wrong list.
    #
    # `test_json_schema.py` already holds the schema against the package, in both directions. The
    # edge nothing held is this one: the schema against the sentence that tells a consumer how to
    # read it.
    schema = json.loads(
        (_ROOT / f"src/elenctic/schema/output-v{SCHEMA_VERSION}.schema.json").read_text(
            encoding="utf-8"
        )
    )
    closed, open_valued = _vocabulary_fields(schema)
    stated = set(re.findall(r"`(\w+)`", _instructed_span("closed enumerations (", ")")))
    assert closed == stated, (
        f"the schema closes {sorted(closed)} with an enum, and the three-tier paragraph "
        f"names {sorted(stated)} as the closed enumerations — a consumer reads that list to decide "
        f"what a version bump means"
    )
    # The open half, in the one direction that matters. A closed field named as open is advice to
    # accept a value the schema will reject; the reverse costs a consumer nothing but caution.
    #
    # The first assertion catches most of that already, and this is not the comfort it looks like:
    # the one cause it cannot see is a document naming a field in *both* paragraphs, where the
    # closed list still matches the schema and the sentence beside it contradicts itself. Measured
    # by provoking exactly that, which is the only way it fires.
    promised_open = set(
        re.findall(r"`(\w+)`", _instructed_span("open-valued string fields — ", "—"))
    )
    assert promised_open, "no document names an open-valued field in the shape this reads"
    assert not promised_open & closed, (
        f"the documents tell a consumer to treat {sorted(promised_open)} as open and to expect "
        f"unfamiliar values, and the schema closes {sorted(promised_open & closed)}"
    )
    assert promised_open <= open_valued, (
        f"{sorted(promised_open - open_valued)} is named as an open-valued string field of "
        f"the document, and the schema has no such string field"
    )


def _instructed_span(opening: str, closing: str) -> str:
    """The text between the first ``opening`` and the next ``closing``, across the documents.

    By the words of the sentence rather than by a line or a heading, because this paragraph is
    prose that wraps: a slice taken by line would move the first time somebody reflowed it, and one
    taken by heading would reach half the section.

    **Both delimiters are required to be there**, and the closing one is the half that matters. A
    ``split`` that does not find its closing text returns everything after the opening instead —
    so a reworded sentence would quietly widen the span to the rest of the document rather than
    narrow it, and a caller counting names in it would be reading every document. Absent, this
    says which sentence moved; present and wrong, the caller's own assertion says the rest.
    """
    holding = [name for name, text in _INSTRUCTIONS.items() if opening in " ".join(text.split())]
    assert len(holding) == 1, (
        f"a span is read out of one document, and {opening!r} is in {holding or 'none of them'}"
    )
    page = " ".join(_INSTRUCTIONS[holding[0]].split())
    after = page.split(opening, 1)[1]
    assert closing in after, f"{holding[0]} no longer says {closing!r} after {opening!r}"
    return after.split(closing, 1)[0]


def _vocabulary_fields(schema: dict[str, object]) -> tuple[set[str], set[str]]:
    """The document's string-valued field names, split into those the schema closes with an ``enum``
    and those it leaves open.

    ``$ref`` is followed, and that is the whole reason this is a function rather than a search for
    the word ``enum``: a check's ``status`` and a case's ``verdict`` are both written as a reference
    to one shared definition, so a reading that stopped at the property would report the closed set
    as four where it is five — and would have called a correct document wrong.
    """
    defs = schema.get("$defs", {})
    assert isinstance(defs, dict)
    closed: set[str] = set()
    open_valued: set[str] = set()

    def resolve(node: dict[str, object]) -> dict[str, object]:
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = defs[ref.removeprefix("#/$defs/")]
            assert isinstance(target, dict)
            return target
        return node

    def walk(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                for name, raw in properties.items():
                    assert isinstance(raw, dict)
                    field = resolve(raw)
                    if field.get("type") != "string":
                        continue
                    (closed if "enum" in field else open_valued).add(name)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return closed, open_valued


def _package_sources() -> list[Path]:
    """Every Python file the package is written in, in a stable order.

    ``rglob``, because the rules below are written about "under ``src/elenctic/``" and a module in a
    subpackage is under it. There is one subdirectory today and it holds the packaged schema rather
    than code — which is the point: this goes on finding them after somebody adds the first
    subpackage. Stated once because two checks read it under different filters, and a second
    spelling of where the source lives is a second thing to keep true.
    """
    return sorted((_ROOT / "src/elenctic").rglob("*.py"))


def _package_modules() -> dict[str, ast.Module]:
    """Every module under ``src/elenctic/`` but the package surface, parsed.

    ``__init__.py`` is excluded because the sentences below exclude it: the guide counts eighteen
    modules "plus the package surface", and that surface names every one of them lazily, so counting
    it would make the graph look like a star with nothing at the bottom.
    """
    return {
        path.stem: ast.parse(path.read_text(encoding="utf-8"))
        for path in _package_sources()
        if path.name != "__init__.py"
    }


def _in_package_imports(tree: ast.Module, known: frozenset[str]) -> set[str]:
    """The modules of this package that ``tree`` imports, by any spelling.

    Three spellings reach the same dependency and all three are in the tree — ``from
    elenctic.result import …``, ``from elenctic import checks``, and a plain ``import``. A reader of
    one form would not predict the others, which is the whole reason this is read from the AST
    rather than matched. Imports written *inside* a function count: the stage entry points import
    lazily, and a dependency deferred to call time is still a dependency, still a cycle if it closes
    one, and still the thing a layer diagram is about.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            # The relative spellings, which are the ones this missed. `from . import checks` names
            # its modules in the aliases and carries no module at all; `from .result import …`
            # carries one that is a bare name rather than a dotted path, so a reader keyed on the
            # package name skips it. Neither is hypothetical hygiene: the lint that would forbid
            # them is not configured here, so both pass the gate, and a *deferred* relative import
            # is exactly the shape that closes a cycle without breaking a single import. A deeper
            # level leaves the package and is nothing to do with this graph.
            if node.module:
                found |= {node.module.split(".")[0]} & known
            else:
                found |= {alias.name for alias in node.names if alias.name in known}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            parts = node.module.split(".")
            if parts[0] != "elenctic":
                continue
            if len(parts) > 1:
                found.add(parts[1])
            else:  # `from elenctic import checks` — the module is a name, not part of the path
                found |= {alias.name for alias in node.names if alias.name in known}
        elif isinstance(node, ast.Import):
            found |= {
                parts[1]
                for alias in node.names
                if (parts := alias.name.split("."))[0] == "elenctic" and len(parts) > 1
            }
    return found


def test_the_layering_the_contributor_guide_describes_is_the_layering_there_is() -> None:
    # The guide calls this "the property worth knowing before you decide where something belongs"
    # and attaches a review rule to it — "a patch that introduces a cycle is a patch that will be
    # asked to move something" — and nothing enforced either. It is the same decay as the module
    # count two tests below, which *is* checked: adding an import is not an edit to a document, so
    # nobody is prompted. The count was held and the structure the count is about was not.
    #
    # Read from the AST, so what is checked is the graph rather than a description of it.
    trees = _package_modules()
    known = frozenset(trees)
    deps = {name: _in_package_imports(tree, known) - {name} for name, tree in trees.items()}

    bottom = sorted(name for name, imported in deps.items() if not imported)
    stated = re.search(
        r"`(\w+)`, `(\w+)`, `(\w+)` and `(\w+)` are the shared vocabulary", _CONTRIBUTING
    )
    assert stated is not None, "the guide no longer names the bottom layer in the shape this reads"
    assert sorted(stated.groups()) == bottom, (
        f"the guide names {sorted(stated.groups())} as the modules that depend on nothing else "
        f"here, and the ones that actually do are {bottom}"
    )

    imported_by_someone = {name for imported in deps.values() for name in imported}
    top = sorted(set(deps) - imported_by_someone)
    assert top == ["cli"], f"the guide says `cli` is alone at the top, and the top is {top}"
    assert "`cli` is alone at the top" in _CONTRIBUTING, "and the guide has to still say so"

    # Acyclic: a module that can reach itself is on a cycle. Stated as the whole set, so a reader of
    # a failure sees every module the cycle runs through rather than the first one found.
    def reaches(start: str) -> set[str]:
        seen: set[str] = set()
        pending = [start]
        while pending:
            for nxt in deps[pending.pop()]:
                if nxt not in seen:
                    seen.add(nxt)
                    pending.append(nxt)
        return seen

    cyclic = sorted(name for name in deps if name in reaches(name))
    assert not cyclic, (
        f"the guide calls this an acyclic layered graph, and these modules are on a cycle: {cyclic}"
    )
    assert "acyclic layered graph" in _CONTRIBUTING, "and the guide has to still claim it"


def test_the_clingo_boundary_the_contributor_guide_draws_is_where_it_says_it_is() -> None:
    # Two claims, one sentence apart, and the guide attaches a review rule to the second: "a patch
    # that puts a solve somewhere else under `src/elenctic/` is a patch that will be asked to move
    # it". The count is the softer half and the one that decays silently; the boundary is the half
    # worth a gate.
    #
    # Both by AST. A grep for an import counts a *comment* about one — which is how an earlier
    # reading of this very count said eight when it was seven, matching a sentence in `discovery.py`
    # that reads "this module imports from clingo".
    trees = _package_modules()
    importers = sorted(
        name
        for name, tree in trees.items()
        if any(
            (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.split(".")[0] == "clingo"
            )
            or (
                isinstance(node, ast.Import)
                and any(alias.name.split(".")[0] == "clingo" for alias in node.names)
            )
            for node in ast.walk(tree)
        )
    )
    # The guide states this over TWO forms — a count, and the seven modules by name — so both are
    # held. One module gaining a clingo import while another loses one leaves the count true and
    # the list wrong, and the list is the half a reader navigates by.
    paragraph = _CONTRIBUTING.split(f"{_IN_WORDS[len(importers)]} modules do", 1)
    assert len(paragraph) == 2, (
        f"{len(importers)} modules import from clingo ({importers}), and the guide does not say "
        f"{_IN_WORDS[len(importers)]}"
    )
    named = set(re.findall(r"`(\w+)\.py`", paragraph[1].split("\n\n", 1)[0]))
    assert named == set(importers), (
        f"the guide's clingo paragraph names {sorted(named)} and the modules that import from "
        f"clingo are {sorted(importers)}"
    )

    building = sorted(name for name, tree in trees.items() if _builds_a_control(tree))
    assert building == ["solvers"], (
        f"the guide says only `solvers.py` constructs a `Control`, and these do: {building}"
    )
    assert "Only `solvers.py` constructs a `Control`" in _CONTRIBUTING, "and it has to still say so"


def _builds_a_control(tree: ast.Module) -> bool:
    """Whether this module constructs a clingo ``Control``, read from what its imports *bind*
    rather than from the identifier a call happens to spell.

    Three spellings reach one constructor: ``from clingo import Control`` and then ``Control(…)``;
    the same import under an alias; and ``import clingo`` with ``clingo.Control(…)``. Matching the
    word ``Control`` catches the first and the third and misses the middle one — which is the
    spelling a reader is least likely to predict, and the one nothing else in the gate has an
    opinion about. Reading the binding covers all three without listing them.
    """
    bound: set[str] = set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "clingo":
            bound |= {alias.asname or alias.name for alias in node.names if alias.name == "Control"}
        elif isinstance(node, ast.Import):
            modules |= {
                alias.asname or alias.name
                for alias in node.names
                if alias.name.split(".")[0] == "clingo"
            }
    return any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in bound)
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "Control"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in modules
            )
        )
        for node in ast.walk(tree)
    )


def _everything_shipped_that_carries_a_sentence() -> dict[str, str]:
    """Every file this repository ships whose bytes are text, keyed by the path a failure names.

    Wider than :func:`_documents_of_instruction`, and deliberately: a number written in words goes
    wherever it is convenient to write one — a module header, the landing page, the shipped JSON
    schema, a comment in this suite — so a reader of the Markdown alone holds the copies least
    likely to drift and misses the ones most likely to.

    ``CHANGELOG.md`` is excluded, on the boundary these checks already draw and for its reason. A
    changelog says what a release did. A sentence describing the release that shipped stays true
    after a later release changes the thing it describes, so requiring it to track the code would
    corrupt the record rather than keep it honest.
    """
    listed = subprocess.run(
        ["git", "-C", str(_ROOT), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    shipped: dict[str, str] = {}
    excluded = "CHANGELOG.md"
    # By basename, which is how :func:`_documents_of_instruction` spells the same exclusion — two
    # spellings of one rule are two rules the day the file moves into a subdirectory. Asserted
    # present, so that a move is a finding here and not merely a missing key somewhere downstream.
    assert any(Path(name).name == excluded for name in listed if name), (
        f"git lists no {excluded}, which this excludes by name. It has moved or gone, and the "
        f"exclusion now applies to nothing"
    )
    for name in listed:
        if not name or Path(name).name == excluded:
            continue
        with contextlib.suppress(UnicodeDecodeError, OSError):
            shipped[name] = (_ROOT / name).read_text(encoding="utf-8")
    assert shipped, "git lists nothing, and a sweep over no files passes every check it feeds"
    return shipped


def _every_concrete(module: str, base: str) -> list[str]:
    """Every class in one module descending from ``base``, however deep, read from its source.

    From the source and not from ``base.__subclasses__()``, which cannot be counted here.
    ``@dataclass(slots=True)`` cannot add slots to a class in place, so it builds a replacement —
    and the original goes on being registered as a subclass until it is collected. That list holds
    each of these shapes *twice*, only one of which is the live class, and how many of the stale
    halves remain depends on when the garbage collector last ran: measured, sixteen entries in a
    bare interpreter and nine under the suite. A count that moves under its reader is worse than
    one that is merely narrow.

    Transitive, so the reading does not quietly rest on each shape being ``@final``.
    """
    bases = {
        node.name: {parent.id for parent in node.bases if isinstance(parent, ast.Name)}
        for node in ast.walk(_package_modules()[module])
        if isinstance(node, ast.ClassDef)
    }
    descends: set[str] = set()
    frontier = {base}
    while frontier:
        frontier = {n for n, p in bases.items() if p & frontier} - descends - {base}
        descends |= frontier
    return sorted(descends)


def test_no_file_this_repository_ships_counts_a_thing_without_saying_how_many_there_are() -> None:
    # A number written out in words decays by the code changing, and nothing prompts the edit. Where
    # the number sits against what it counts, whoever is reading that spot can see both, and
    # proximity is the whole of what holds it. Proximity holds nothing for the same number in the
    # landing page, the shipped schema, another module's header, or a comment in this suite.
    #
    # **Per file, and that is the whole strength of it.** Asking only that the total appear
    # *somewhere* is an existential, and the person adding a field discharges it at the one copy
    # proximity was already holding: the count beside the record goes to four, six other files go on
    # saying three, and every one of them reads as counting a part rather than as stale. So the
    # obligation is on each file that counts the thing at all — say how many there are, and then say
    # whatever else is true. Every file passes that today, so it costs no sentence anything.
    #
    # A part may still be counted, alongside the total and in the same file: one record's header
    # speaks of the pair a dry run shares with a run, and a dial is offered by fewer than all the
    # command words. What may not happen is a file counting more than there are, or counting some of
    # them while never saying how many there are.
    #
    # Each count is asked of the thing itself rather than read off the source, because "the names a
    # class body binds" is not the same question: a `ClassVar` is not a register, an enumeration
    # alias is not a further command, and a field moved onto a shared base is still a field.
    #
    # The phrase is matched rather than the bare noun. `shapes` is written here of contracts, of
    # queries, of projections and of the concrete answer-set carriers — four populations, with a
    # different true count each — so it needs the qualifier to pick out the intended sense. The
    # other two nouns have homonyms that do not collide today (`registers` is also a verb, and a
    # `command` is also a line one types); a number word landing in front of either is the signal to
    # give that entry a qualifier too.
    counted = (
        (r"(\w+) registers", [field.name for field in dataclasses.fields(RunOutcome)]),
        (r"(\w+) commands", [command.name for command in _Command]),
        (r"(\w+) concrete (?:Consistent )?shapes", _every_concrete("result", "Consistent")),
    )
    shipped = _everything_shipped_that_carries_a_sentence()
    for pattern, members in counted:
        assert len(members) < len(_IN_WORDS), (
            f"{members} runs past the end of the table that spells a count out in words, so the "
            f"reading below would fail as an index error rather than as the finding it is"
        )
        spelled = _IN_WORDS[len(members)]
        counting = {}
        for name, text in shipped.items():
            words = {w.lower() for w in re.findall(pattern, text, re.I) if w.lower() in _IN_WORDS}
            if words:
                counting[name] = words
        assert counting, (
            f"nothing this repository ships spells out a count for {pattern!r}, so this is holding "
            f"nothing. The sentence moved, and this entry has to follow it or go"
        )
        silent = {name: sorted(words) for name, words in counting.items() if spelled not in words}
        assert not silent, (
            f"the code has {len(members)} of these ({members}), and these files count them without "
            f"ever saying {spelled!r}: {silent} — matched by {pattern!r}"
        )
        over = {
            name: sorted(w for w in words if _IN_WORDS.index(w) > len(members))
            for name, words in counting.items()
        }
        over = {name: words for name, words in over.items() if words}
        assert not over, (
            f"the code has {len(members)} of these ({members}), and these files claim more: "
            f"{over} — matched by {pattern!r}"
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


# A name written as code inside prose — one or two backticks around it, RST's spelling and the
# comments'. What is read out of the span is the dotted path it opens with, so ``_lex``,
# ``_finish()`` and ``Check._judge`` all answer with the names a reader would search for.
_AS_CODE = re.compile(r"``?([^`]+)``?")
# What an attribute docstring can stand under — the statements that give a name a value, and so the
# only ones a string beneath can be documenting.
_BINDS_A_VALUE = ast.Assign | ast.AnnAssign | ast.TypeAlias
_DOTTED_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


def _prose_in(path: Path) -> list[tuple[str, int, str]]:
    """Every docstring and comment in one module, labelled, each with the line a failure names.

    Parsed rather than matched, because each form has a lookalike the characters cannot tell apart:
    a ``#`` inside a string literal is not a comment, and a string handed to something — an
    argument, a table entry, a default — is a value and not prose. ``tokenize`` and ``ast`` each
    decide their half the way Python does.

    **Three forms, because this package writes prose in three.** A scope's own docstring; an
    *attribute* docstring, the bare string standing under an assignment, which is how
    ``SCHEMA_VERSION``, ``type Outcome`` and the graded-record enums are documented and which
    ``ast.get_docstring`` does not return; and a comment. Attribute docstrings sat outside this
    reader until it was widened, and a phantom injected into one of them was carried green.

    A bare string under something that binds nothing documents nothing, and is not returned. The
    difference is load-bearing rather than tidy: the emptiness check below leans on the attribute
    form because that form's *hits* are legitimately empty, so a label handed to any loose string
    would let a stray one stand in for the population the check is about.

    Labelled because the check below holds each form against its own emptiness. A reader that lost
    one of them goes on returning the others' hits, so an assertion over the union stays green while
    a form's worth of prose is unread — and the defect that motivated all this lived in a docstring.

    What this reads is the package's Python, and the rest is stated so it is not mistaken for
    covered. ``schema/output-v2.schema.json`` ships prose of its own, in a hundred-odd backticked
    spans that other checks here hold; so do argparse's help strings and the diagnostics, which are
    string literals in value position rather than prose. None writes a private name today. Within a
    docstring, implicitly concatenated fragments are one constant to the parser, so a name in the
    second fragment is reported at the first fragment's line; the package writes none.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    documented: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        scope = isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        for field, block in ast.iter_fields(node):
            if not isinstance(block, list):
                continue
            for index, statement in enumerate(block):
                if not isinstance(statement, ast.Expr):
                    continue
                if not isinstance(statement.value, ast.Constant):
                    continue
                if not isinstance(statement.value.value, str):
                    continue
                if index == 0 and scope and field == "body":
                    kind = "docstring"
                elif index and isinstance(block[index - 1], _BINDS_A_VALUE):
                    kind = "attribute"
                else:
                    continue
                documented.append((kind, statement.lineno, statement.value.value))
    return documented + [
        ("comment", token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT
    ]


def _private_names_written_in(prose: str) -> list[tuple[int, str]]:
    """The package-private names one piece of prose writes as code, each with the line it is on
    counted from the start of that prose.

    **Every segment of a dotted path, not the one it opens with.** The shape this package writes is
    a private member of a *public* owner — ``Check._judge``, ``solvers._FACADES``,
    ``run._query_mode``, ``checks._braces`` — and a reader keyed on the opening identifier throws
    the whole span away because ``Check`` is public, leaving the private half unheld. Five such
    names were invisible until this was widened: the motivating defect's own shape, sitting in the
    population a first measurement had reported as empty.

    The offset rather than the block, because a docstring here runs to sixty lines and a failure
    reporting the line the *docstring* opens on points a reader at a paragraph rather than at a
    name — which is the kind of not-quite-true coordinate the rest of this module exists to catch.

    A ``__dunder__`` is not one of these names. Python's own reference calls those system-defined
    and tells nobody to invent one, so ``__repr__`` and ``__cause__`` in a sentence about protocol
    behaviour are the interpreter's and nothing for a check about this package to hold. The limit
    that leaves is worth naming: an invented ``__contract__`` is skipped too, on the strength of a
    prohibition rather than a check. The single leading underscore and the class-private ``__name``
    are the package's own, and both are held.
    """
    written = []
    for span in _AS_CODE.finditer(prose):
        dotted = _DOTTED_PATH.match(span.group(1).strip())
        if dotted is None:
            continue
        at = prose.count("\n", 0, span.start())
        written += [
            (at, segment)
            for segment in dotted.group().split(".")
            if segment.startswith("_") and not (segment.startswith("__") and segment.endswith("__"))
        ]
    return written


def _names_the_package_binds() -> set[str]:
    """Every name the package's own source binds, by any spelling it can be bound under.

    A binding rather than a mention, and the distinction is the whole reason this is read from the
    source rather than matched: reading ``model.type`` off one of clingo's objects does not make
    ``type`` a name this package defines, so an attribute counts where it is assigned and not where
    it is read.

    **Two readers, because there are two authorities and neither answers for the other.**

    ``symtable`` is Python's own answer to what a piece of source binds — it is the compiler's
    symbol table, so it covers every binding form the language has, including the ones an
    enumeration of AST arms forgets. This one did: ``def``, ``class``, assignment, parameter,
    import alias and ``global``/``nonlocal`` were listed as *every other form that binds*, and the
    package was already using three that were not on it — ``case shape:`` (26 sites),
    ``except OSError as exc`` (22) and PEP 695 type parameters (6). None of them binds a private
    name today, so nothing was wrongly reported; the claim was simply false, and the day someone
    writes ``except OSError as _exc`` it becomes a phantom this gate invents. An authority is not a
    longer list — it is the thing that cannot be short.

    Attributes are the half ``symtable`` does not answer, and correctly so: ``self._attr = 2`` binds
    no *symbol*, and clingo's ``model.type`` must not become a name this package defines. So the
    AST supplies exactly the ``Attribute`` stores, which is how ``_value_`` — assigned onto a
    foreign protocol field in ``outcome.py`` — is a name a reader searching for it can find.

    The module basenames join both, because prose writes ``solvers.py`` as a name too.
    """
    bound = {path.stem for path in _package_sources()}

    def symbols(table: symtable.SymbolTable) -> None:
        for symbol in table.get_symbols():
            if symbol.is_assigned() or symbol.is_parameter() or symbol.is_imported():
                bound.add(symbol.get_name())
        for nested in table.get_children():
            symbols(nested)

    for path in _package_sources():
        text = path.read_text(encoding="utf-8")
        symbols(symtable.symtable(text, str(path), "exec"))
        bound |= {
            node.attr
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
        }
    return bound


def test_every_private_name_the_source_prose_writes_is_one_the_package_defines() -> None:
    # A name written as code is a promise a reader can search for it. `expectation.py` opened its
    # "Four responsibilities" by naming `_comments` as the module's one comment reader, and no
    # commit ever defined it. Born false rather than left behind by a rename — so the standing care
    # about moving code with its prose could not have caught this, and nothing else could either.
    #
    # Private names only, and that narrowness is the whole of why this holds rather than nags. The
    # general form — every backticked name resolves — reports Python's builtins and keywords,
    # clingo's API, stdlib parameter names, ASP predicates and the single letters standing for
    # terms: none of them defined here, every one of them correctly written. It would ship with an
    # exemption list. A leading underscore has nowhere to resolve but here, which is what makes the
    # narrow rule answerable at all.
    bound = _names_the_package_binds()
    prose = [
        (kind, path.name, opens, text)
        for path in _package_sources()
        for kind, opens, text in _prose_in(path)
    ]
    written = [
        (kind, module, opens + offset, name)
        for kind, module, opens, text in prose
        for offset, name in _private_names_written_in(text)
    ]

    # Two ways this can pass while holding nothing, and they are held apart because a single
    # assertion over the union lets either answer for the other.
    #
    # A form of prose the reader stopped reaching. For the attribute form this is the *only*
    # available guard: no attribute docstring writes a private name today and none need ever, so
    # its hit set is legitimately empty and cannot stand in for its population.
    read = {kind for kind, *_ in prose}
    assert read == {"attribute", "comment", "docstring"}, (
        f"the reader returned prose of {sorted(read) or 'no form'}, where this package has written "
        f"it in all three. Either a form is going unread — in which case a green run here says "
        f"nothing about it — or the package has stopped writing that form, and this line is what "
        f"has to be revised to say so"
    )
    # A matcher that stopped matching. Superset, not equality: an attribute docstring that comes to
    # write a private name is correct prose, and a guard that forbids it would be holding the
    # codebase to the shape it had when the guard was written.
    found_in = {kind for kind, *_ in written}
    assert found_in >= {"comment", "docstring"}, (
        f"private names as code were found in {sorted(found_in) or 'no form'}, and this package "
        f"writes them in its docstrings and its comments alike — so the matcher is reading past "
        f"one of them, and a green run holds only the other"
    )

    phantom = sorted(
        f"{path}:{line} `{name}`" for _, path, line, name in written if name not in bound
    )
    assert not phantom, (
        f"prose writes a private name the package does not define: {phantom}. Whatever the "
        f"sentence says about it, a reader who searches for the name finds nothing"
    )


def _every_exception_this_package_defines() -> set[str]:
    """Each exception class elenctic defines, under every dotted name a reader can import it by.

    Both names, because ``ruff`` resolves a class to the qualified name the *import* spells and does
    not follow a re-export: a test writing ``from elenctic.program import ProgramError`` is asking
    about ``elenctic.program.ProgramError``, and one writing ``from elenctic import ProgramError``
    is asking about ``elenctic.ProgramError``. A list carrying only the defining module's spelling
    holds every test in the suite today and none of the ones that import from the curated surface,
    which is the half a reader is likelier to reach for.

    Walked rather than read off ``__all__``: what the setting is about is what the package
    *defines*, and a class held back from the curated surface is still one a test can import and
    still one a bare ``raises`` passes on.
    """
    defined = {
        obj
        for module in [elenctic, *_submodules()]
        for obj in vars(module).values()
        if isinstance(obj, type)
        and issubclass(obj, BaseException)
        # The package itself as well as everything under it: a class defined in ``__init__.py``
        # carries the bare package name, and a prefix test alone would let that one class out of
        # the derivation without anything saying so.
        and obj.__module__.split(".")[0] == elenctic.__name__
    }
    return {f"{obj.__module__}.{obj.__qualname__}" for obj in defined} | {
        f"{elenctic.__name__}.{obj.__qualname__}"
        for obj in defined
        if obj.__qualname__ in elenctic.__all__
    }


def _submodules() -> list[object]:
    """Every module inside the package, imported, so walking their contents reaches them all."""
    return [
        importlib.import_module(found.name)
        for found in pkgutil.walk_packages(elenctic.__path__, f"{elenctic.__name__}.")
    ]


def test_the_lint_asks_for_a_match_on_every_exception_this_package_defines() -> None:
    # A require-list is an allow-list wearing the other sign, and it decays the same way: a class
    # added next year is one the gate does not ask about, which is exactly how the convention this
    # setting exists to enforce came to be honoured in some places and not others. The guide has
    # asked for a `match=` on elenctic's own families for two releases; over that time the count of
    # `pytest.raises` written without one grew rather than shrank, because nothing could ask.
    #
    # So the setting is derived and checked rather than maintained. What it names is a property of
    # the package, and the package is asked for it here rather than a reader being trusted to
    # remember. The message prints the set it derived, so the repair is a paste rather than a hunt.
    manifest = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    asked = manifest["tool"]["ruff"]["lint"]["flake8-pytest-style"]
    required = set(asked["raises-extend-require-match-for"])
    assert required, "the setting is empty, and every exception this package defines is unasked"

    defined = _every_exception_this_package_defines()
    assert required == defined, (
        "the lint and the package disagree about which exceptions must be matched on.\n"
        f"unasked about: {sorted(defined - required)}\n"
        f"named and undefined: {sorted(required - defined)}\n"
        f"the setting should read:\n{sorted(defined)}"
    )


# Anywhere on the line, not anchored to its start. Written anchored first, and four of the six
# spellings a Markdown document actually uses walked straight past it: an inline code span, a list
# item, a block quote, and `from elenctic . result import X`, which Python accepts. A document
# instructs an import wherever the words appear, so that is what is matched.
_SUBMODULE_IMPORT = re.compile(
    r"from\s+elenctic\s*\.\s*(\w+)\s+import\b|import\s+elenctic\s*\.\s*(\w+)"
)


def test_no_document_tells_a_reader_to_import_from_a_submodule() -> None:
    # The version promise has a subject, and this is what keeps it true. `docs/library-api.md` says
    # the supported surface is what `import elenctic` gives you, and that a name reached through a
    # submodule is internal and may change in a patch release. A document that then shows
    # `from elenctic.result import ConsistentWitness` has told a reader to depend on something the
    # same document says they may not — and the reader who followed it is broken by a patch we were
    # entitled to ship.
    #
    # An import *statement*, not a mention: prose naming `elenctic.solvers` while saying where a
    # thing lives is how these documents explain the package, and is not what the promise is about.
    #
    # `CHANGELOG.md` is outside `_documents_of_instruction` and correctly so — a changelog must be
    # able to say which module a thing moved out of, and this rule would forbid it.
    instructed = [
        (where, match.group(0).strip())
        for where, text in _INSTRUCTIONS.items()
        for match in _SUBMODULE_IMPORT.finditer(text)
    ]
    assert _INSTRUCTIONS, "no documents were swept at all, so this passes by knowing nothing"
    assert not instructed, (
        f"these send a reader into a submodule, which the version promise does not cover: "
        f"{instructed}. The supported surface is `import elenctic`; if one of these names is worth "
        f"promising, it belongs in `_EXPORTS` rather than in a document"
    )


_STATED_SCHEMA_VERSION = re.compile(r'"schema_version":\s*(\d+)|output-v(\d+)\.schema\.json')


def test_the_schema_version_the_documents_show_is_the_one_the_package_ships() -> None:
    # The worked document is what a consumer copies to write their reader against, and the number in
    # it is the one they dispatch on. Nothing held it: setting it to 3 while the package shipped 2
    # left every one of these tests green, which is how a document comes to describe a release that
    # never existed.
    #
    # Both spellings the version is written down in — the field a document carries, and the name of
    # the schema file that describes it — so that a document naming the file is held too. **No
    # document names the file today**, so that arm currently guards an empty set; it is here because
    # the guide is where such a sentence would land, not because one exists. The package derives its
    # own file name from the same constant (`json_report.schema_text`), so both arms are derived
    # rather than kept in step by hand.
    #
    # A number in *prose* is deliberately not matched, and that is a limit rather than an oversight:
    # the guide says the version "went from 1 to 2 between 0.3.0 and 0.4.0", which is history and
    # stays true forever. Widening this to prose — the obvious next improvement — would force that
    # sentence false at the next bump.
    stated = [
        (where, int(field or filename))
        for where, text in _INSTRUCTIONS.items()
        for field, filename in _STATED_SCHEMA_VERSION.findall(text)
    ]
    assert stated, (
        "no document states a schema version at all — the worked document has lost the field a "
        "consumer dispatches on, or this pattern is no longer the pattern"
    )
    adrift = [(where, shown) for where, shown in stated if shown != SCHEMA_VERSION]
    assert not adrift, (
        f"the package ships schema_version {SCHEMA_VERSION} and these say otherwise: {adrift}. A "
        f"reader writing against the worked document would branch on a version that is not shipped"
    )
