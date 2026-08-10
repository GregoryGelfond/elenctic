# Contributing to elenctic

Thanks for looking. Bugs, questions and patches are all welcome: bugs and questions on the
[issue tracker](https://github.com/GregoryGelfond/elenctic/issues), patches as pull requests.

elenctic is MIT-licensed. There is no contributor agreement to sign.

**Using an AI assistant is fine.** Claude or anything else, for any part of it — some projects
disallow this and elenctic does not, and there is nothing you need to disclose. The one thing that
does not change is that the contribution is yours: you are the one vouching for it, and it is read
on the same terms as anything else.

**The assistant's own files must not go in, though.** No `.claude/`, `.serena/`, `.cursor/` or the
equivalent; no assistant instruction files; no session transcripts, generated plans or working
notes. Whatever your tooling keeps beside your checkout stays out of the commit — it is
configuration for how *you* work, and someone cloning elenctic should find the project rather than
anyone's setup. Stage the paths you mean rather than reaching for `git add -A`, which is how these
arrive by accident.

If it helps, the conventions further down are the ones worth pointing an assistant at. Several of
them are there because a confident, plausible, wrong answer got as far as a commit in this
repository — a failure mode people and assistants share, and the reason the gate is shaped the way
it is.

## Getting set up

The toolchain is pinned with [pixi](https://pixi.sh), which brings its own Python, clingo and
clingcon — you do not need any of them installed already. The pinned environment resolves for
**macOS on Apple silicon and Intel, and Linux on x86-64** — `osx-arm64`, `osx-64` and `linux-64`,
which is the list in `pixi.toml` — and CI runs on Linux and macOS. Anything else, Windows and
64-bit ARM Linux included, is not in the set, so `pixi install` will fail there rather than build
something untested.

**64-bit ARM Linux is absent for a reason worth knowing, since it is otherwise the obvious
omission:** conda-forge packages clingo for `linux-aarch64` but **not clingcon**, so the
environment cannot be solved there — `pixi` reports no candidates for it. That is upstream
packaging rather than a decision here, and it is why the platform list is not simply widened. If
you want a platform that is missing, say so on the issue tracker rather than carrying a local
patch: it is a change to the lock file and the CI matrix, and for this one it needs a clingcon
build that does not yet exist.

```console
$ git clone https://github.com/GregoryGelfond/elenctic
$ cd elenctic && pixi install
$ pixi run check
```

`pixi run check` is the whole gate, and it is exactly what CI runs on Linux and macOS. It is three
things: `ruff check` plus `ruff format --check`, `mypy` under `--strict`, and `pytest`. Run it
before you open anything; if it is green locally it should be green in CI, and when it is not, that
difference is itself worth reporting.

Individual pieces, when the whole gate is more than you need:

```console
$ pixi run test         # pytest
$ pixi run lint         # ruff check + ruff format --check
$ pixi run typecheck    # mypy --strict
$ pixi run cov          # pytest with a coverage report
$ pixi run fmt          # apply the formatting `lint` checks for
```

`lint` reports formatting it will not apply, so `fmt` is the other half of it: `pixi run fmt` then
`pixi run lint` is the whole of that loop. For the lint half, `ruff check --fix` applies what can
be applied safely. **Do not reach for `--unsafe-fixes` to make the gate green** — the fix it unlocks
for `T20` is to *delete* the `print`, which is not what anyone means by fixing a lint about it.

**Python 3.14 is a deliberate floor**, not an accident of what was current. The implementation uses
3.14 idioms that are load-bearing rather than decorative, so patches may use them freely.

## Reporting a bug

The most useful report contains the `.lp` file — contract and program — that provokes it, what you
expected, and what elenctic said. If elenctic named the **harness** locus — `HARNESS ERROR —` for
one case, `harness error:` where it cost the whole run — please report it: that word means
elenctic violated one of its own invariants, and it is ours to fix rather than yours.

If you can, include the output of `elenctic run <target> --format json`, which carries the same run
in a form that does not depend on how your terminal rendered it.

## What the gate holds you to

**`mypy --strict`, plus two settings beyond it.** `warn_unreachable` and `possibly-undefined` —
the second because a fault handler runs precisely because something above it did not finish, so a
name bound up there may be unbound down here, and the failure then arrives as a second error
raised while reporting the first. (`strict_equality` is set in `pyproject.toml` too, but it is
already inside `--strict`; it is written out because it is load-bearing here, not because it adds
anything.)

**A lint selection chosen by measuring, not by reputation.** Most of the families in
`pyproject.toml` were already clean when they were adopted, so they hold a property the code has
rather than asking for new work. Two exceptions are worth knowing about before they surprise you:

- **`T20` forbids `print`** everywhere except the modules that are meant to write to a terminal —
  the command line, the renderer that turns a run into prose, the streams layer the command line
  hands standard output over through, and the four whose documented
  `python -m elenctic.<module> <file.lp>` entry prints an inspection of one stage. They are listed
  in `pyproject.toml`. If you want to see something while debugging, use a module logger; the
  library writes to no stream, and that is a guarantee its callers rely on.
- **`RET501` is switched off in `corpus.py`**, and only there. The observer protocols spell their
  no-op default bodies `return None`, which the rule objects to — but mypy treats a body that is
  only a docstring as *implicitly abstract*, which would make every announcement mandatory for
  anything inheriting the protocol. The comment in `pyproject.toml` says so at the point of the
  exception.

## Conventions worth knowing

These are not enforced by the gate, and following them will make a patch much easier to take.

**A test's name is a sentence, and a comment above it states the defect it guards.** That is why
`D103` (a docstring on every function) is deliberately not selected: a name and a reason are two
statements already, and a docstring would be a third. Test *modules* do carry a docstring saying
what they hold, and that one *is* enforced.

**Assert the whole line, not a substring of it.** This has cost real time here more than once: six
diagnostic labels were once free to be swapped because the only assertion was over the message,
which every code path passes through unchanged. If what you are pinning is what a reader sees,
compare against the whole of it.

**A test that asserts something is refused should check the input really is faulty.** A green test
can defend a bug — two cases in one test here asserted that valid programs were rejected, and the
rejection was the defect. Relatedly, give `pytest.raises` a `match=`: without one it passes on any
exception of that class raised anywhere underneath, including for a reason that has nothing to do
with what is being rejected. The lint asks for one on the broad built-in families (`ValueError`,
`OSError`, `Exception`) and cannot ask on elenctic's own — write one there anyway.

**Comments say *why*, and are self-contained.** A reader of this repository has the repository and
nothing else — so no `see §3.2`, no `per decision #131`, no milestone or task numbers, and no
reference to a discussion that happened somewhere they cannot read.

**Changelog entries land under `[Unreleased]` as work merges**, not at release time; cutting a
release renames and dates that section. Write for someone deciding whether to upgrade — what
changed for them, and what it means — rather than summarizing the diff. If your change moves
anything a script might match on, say so plainly and give the before and after.

**Never hand-write a transcript.** Run the command and paste what it printed, verbatim, including
the indentation — do not retype it or tidy it. One that was typed out by hand was indented two
columns short of what the tool actually prints, and a reader would have chased the difference;
another was compacted onto fewer lines "for readability" and then described output no invocation
produced. Only one block is mechanically held — the README's library example is extracted and
executed by `tests/test_documentation.py` — so the rest is on you.

**The corpus to try things against is the project's own.** `pixi run elenctic run tests/krbook/encodings`
runs four programs from the Gelfond and Kahl textbook end to end; `--strict` and the `explain`
command are the two things worth trying on it first.

**Names in the documents are checked, and so are the command lines.** A dotted name written as
`` `elenctic.run_corpus` `` in the README, this guide or the changelog is verified to name the
place that thing actually lives — so writing them dotted gets you that check for free. Every
command line either document shows a reader is also run past the argument parser and must be one it
accepts, so a flag that moves cannot leave an example behind. What counts as one: a line at a `$`
prompt, and a backticked span read from the word `elenctic` onward — including where it sits inside
a longer command, so the `pixi run elenctic` form a few paragraphs up is checked too. The bare
name carrying no arguments is not a command line, since that is also how these documents write the
program's name. The changelog is deliberately outside this second check: it has to be able to name
the spelling that *stopped* working, which is the one thing the check forbids.

## Where things are

`src/elenctic/` holds eighteen modules, plus the package surface in `__init__.py`. They form an
**acyclic layered graph**, which is the property worth knowing before you decide where something
belongs: `display`, `registry`, `streams` and `terms` are the shared vocabulary at the bottom and
depend on nothing else here; `cli` is alone at the top; and between them each module depends only
on layers below it. So there is an order a reader can walk, and a patch that introduces a cycle is
a patch that will be asked to move something. It is not a straight line — several modules sit
side by side on the same layer — so no single module is "the top" of it but `cli`.

Each of `expectation`, `run`, `discovery` and `solvers` is runnable on its own for inspection:

```console
$ pixi run python -m elenctic.expectation <file.lp>      # the parsed contract
$ pixi run python -m elenctic.run <file.lp>              # the derived run plan
$ pixi run python -m elenctic.discovery <file-or-dir>    # the discovered cases
$ pixi run python -m elenctic.solvers <MODE> <file.lp>   # one solve's outcome
```

`solvers.py` is the only module that **runs a solve**, and that boundary is sharper than "it uses
clingo" — seven modules do, three different ways. Only `solvers.py` constructs a `Control`;
`program.py` and `terms.py` use clingo's *parser* (to read a program's text and to read one term
out of a contract); and those two plus `checks.py`, `expectation.py`, `query.py` and `result.py`
use clingo's *symbol* vocabulary, which is values rather than solving. Everything above
`solvers.py` is a pure function of what it returned, and a patch that puts a solve somewhere else
under `src/elenctic/` is a patch that will be asked to move it.

That rule is about `src/elenctic/` and not about `tests/`, where several modules construct a
`Control` directly to set up or confirm a solver behaviour. `tests/spikes/` is the deliberate home
for the confirming kind — its whole job is to pin the clingo and clingcon behaviour elenctic relies
on — but it is not the only test that drives clingo, and nothing stops a test from doing so.

`tests/` mirrors that shape. `tests/krbook/` vendors four programs from the Gelfond and Kahl
textbook, checked end to end against the semantics they are published with.

Three things about `tests/` that are easy to trip over:

- **`tests/support.py`** holds the shared scaffolding — running elenctic as a real process,
  capturing both streams, decoding a document. `tests/` is on the path, so `from support import …`
  works. A CLI test that re-invents stream capture is a test that will be asked to use it.
- **`tests/spikes/`** confirms clingo and clingcon behaviour elenctic relies on. It is collected by
  the suite, carries the project's one marker (`@pytest.mark.spike`, declared in
  `tests/conftest.py`), and is **excluded from mypy**. The suite runs under `--strict-markers`, so
  a marker you have not declared is an error rather than a warning.
- **Line length is 100**, and mathematical Unicode in comments and docstrings (`⋂ ⋃ ⊆ ∅ ∈`) is
  deliberate house vocabulary — the ambiguous-Unicode lint rules are switched off for it, so it is
  not an accident to be tidied away.

## Opening a pull request

Green gate, and a changelog entry if the change is visible to anyone using elenctic. Beyond that:
say what the change is for, and if it changes behaviour, show the before and the after. A small
patch with a failing test attached is easier to take than a large one without.
