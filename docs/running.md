# Running a corpus

**For:** anyone running elenctic over a directory of encodings, by hand or in CI. Assumes you
have it installed — see the [README](../README.md).

## Discovery

Discovery is **content-keyed**: a `.lp` file is a *case* iff it carries a contract (any known
`@`-tag), otherwise it is a *library* (an `#include` target, never run directly). A directory is
walked for contract-bearing files; a single file is run directly. The program under test is the case
file plus its resolved `#include`s, and the solver is **declared** in the contract
(`% @elenctic solver clingcon`, default `clingo`; clingcon is the optional theory solver — see
the [README](../README.md) for installing it), never inferred from a filename. An undeclared
theory program is a loud error: elenctic never silently mis-solves a theory program under plain
clingo.

Two more rules belong here, because both are decided while the corpus is walked. **A case may only
`#include` files from inside the corpus it belongs to** — a corpus is run as given, so an include
reaching past it would read a file the run was never pointed at. And **naming a contract-free file
directly is a loud error**, although the same file inside a walked directory is simply a library:
tolerance belongs to the walk, not to the one file you pointed at, where a summary saying nothing
ran would bury the only thing that was asked about.


## Running

The standalone runner discovers cases under a target (a single `.lp` file or a directory) and runs
them:

```console
$ elenctic run TARGET          # TARGET defaults to tests/; `elenctic --help` lists exit statuses
$ elenctic run tests/feasible.lp   # run a single case file
$ elenctic explain tests/          # narrate the derived run plan, without solving
$ elenctic run tests/ --strict     # fail the run on any corpus-hygiene issue (the CI gate)
$ elenctic run tests/ --budget 60      # per-solve time limit (default 30s)
$ elenctic run tests/ --deadline 600   # once solving has run 10 minutes, start no more cases; those not reached are reported as not run
$ elenctic run tests/ --format json    # the machine-readable report
$ elenctic schema                      # the JSON schema of that report, without running anything
```

`--budget` and `--deadline` each take a **positive finite** number of seconds: a run that wants no
practical per-solve limit asks for a large number, and one that wants no deadline leaves the flag
off. What each of them actually bounds is worth knowing before you rely on either — see *What the
bounds actually bound* below.

**The two streams are split under every format, not only under `--format json`.** Standard output
carries the *report* — the rendering of each case that did not pass, and the tally. Standard error
carries everything *about* the run: the per-case error lines, the corpus-hygiene block, and the
notice that a deadline stopped it. So `elenctic run tests/ | tee ci.log` keeps `0/3 passed, 2 could
not be run` and loses which two and why; `elenctic run tests/ > ci.log 2>&1` keeps both.

**What `--strict` fails a build on** is corpus hygiene, and there are exactly two observations: an
**orphan library** (a contract-free `.lp` that no case `#include`s — a forgotten case, or dead
code), and an **undeclared solver** (a case that did not say which solver it wants, so it got the
default). Without `--strict` the first is a warning and the second is recorded silently; under
`--strict` both become errors and the run exits `2` however every contract fared. Nothing else
changes: a verdict is never affected by the flag.

Each pipeline stage is also runnable for inspection: `python -m elenctic.expectation FILE.lp`
(the parsed contract), `python -m elenctic.run FILE.lp` (the derived run plan),
`python -m elenctic.discovery FILE-OR-DIR` (the discovered cases), and
`python -m elenctic.solvers MODE FILE.lp` (one solve's outcome, with clingo).


## The dry run

`elenctic explain` shows how each tag is routed to a solver run and the fields it reads, *without
solving*, and whether that run collapses its answer sets onto the shown atoms — which is what
`projects` reports. It is `yes` only under a theory solver, since that is the only place the
collapse can lose anything; a plain clingo run is `no` because there is nothing behind the shown
view to lose, not because a projection was declined. The contract in the README's first example
needs three runs (a full enumeration for `@count`, and the native cautious and brave runs):

```console
$ elenctic explain encodings/drinks/
encodings/drinks/drinks.lp [clingo]
    ENUM_ALL (projects: no):
        @count — reads {full census}
        @expect sat — reads {—}
    CAUTIOUS_ALL (projects: no):
        @cautious ({ biscuit }) — reads {cautious}
    BRAVE_ALL (projects: no):
        @brave ({ coffee, tea }) — reads {brave}
```

A tag a contract may write more than once is shown with the claim it carries, so two lines making
different claims are told apart before anything is solved. Two lines making the *same* claim are
not: the dry run shows what each check reads, and they read the same thing. A verdict names the
line, so the report tells them apart even when the plan cannot.


## The verdict

Each check yields a three-valued **Verdict** about the program under test:

- **PASS** — the contract holds.
- **FAIL** — the program decided *wrong*: the contract is violated by a search good enough to
  settle what this check asks.
- **UNDECIDED** — the check could not be settled: the time budget was hit before the solve decided
  anything, the solver gave up without an answer, or the solve did decide but over a search that
  stopped before covering what this check reads. None of the three is **ever** `FAIL` and none is
  **ever** `UNSAT`: "could not decide" and "decided wrong" are different facts. The third case is
  why a partial search is not read: `@cautious` over part of the answer-set collection yields a
  *superset* of the true intersection, so a false claim would be satisfied by it.

  Note that only the checks whose reading needs more of the search go `UNDECIDED`. A budget hit
  after the solve has decided satisfiability leaves `@expect sat` decided, because one model
  settles it whatever the rest of the search would have found.

A case passes iff every check passes. Errors are a separate register, never verdicts, and they are
reported loudly and distinctly rather than as a costumed `FAIL`. Each is filed under a **locus** —
where the fault lies, which is the word a diagnostic leads with and the `kind` a machine-readable
report carries:

| locus | what is wrong | whose |
| --- | --- | --- |
| `contract` | the `@`-contract is ill-formed | yours |
| `discovery` | the corpus is mis-shaped: a target that does not exist, or a discovery-time precondition | yours |
| `environment` | the machine cannot do what the corpus asks: a declared solver that is not installed, or an installation of elenctic missing its own data files | yours |
| `program` | the program will not load, ground or solve — an unresolvable `#include`, an unsafe variable | yours |
| `containment` | the case `#include`s a file from outside the corpus it belongs to | yours |
| `deadline` | the run's `--deadline` passed before this case was tried | yours |
| `resource` | the case ran out of memory | yours |
| `harness` | elenctic violated one of its own invariants | **ours** |

Loci name *places*, not exception classes, and deliberately: a deadline raises no exception at all
and a resource running out arrives as a built-in — and the mapping is not one-to-one in the other
direction either, since `elenctic.SolverUnavailableError` is a `DiscoveryError` by inheritance while
the fault it reports belongs to the environment, and `elenctic.ContainmentError` is that shape
mirrored — a `ProgramError` by inheritance, filed under a locus of its own because one rule met at
two moments (while the escaping file is read, or while it is grounded) must not reach a reader as
two different problems. Six of the eight do have an exception a library consumer can catch:
`elenctic.ContractError`, `elenctic.DiscoveryError`, `elenctic.ProgramError`,
`elenctic.ContainmentError`, `elenctic.HarnessError`, and `elenctic.SolverUnavailableError`. The
last two of those are subclasses, so either idiom works: catch the parent to treat a family alike,
or the child to answer one member differently — a case reaching outside its corpus is a question
about the corpus you were given, not about how one encoding is written, and a runner may well want
to stop for it. The remaining two have no class to catch by design: a deadline raises no exception
at all, and a resource running out arrives as a built-in. The one closed question about a locus is
`is_elenctic_bug` on `elenctic.ErrorKind` — whether to report it or fix it — and that is what the
exit status reads, so a locus added later never changes what a status means. A case that cannot be
run does not stop the others: it is reported on its own and the rest of the corpus still runs.


## What the bounds actually bound

Four limits are worth stating plainly rather than leaving to be discovered. The first is the one
that bounds nothing; the last is the one to read first if an honest `@count` comes back `UNDECIDED`.

**Grounding is not bounded at all.** A program can be small and still ground to something enormous,
and clingo offers no way to cap that — it is not a limit elenctic can lift. Running an untrusted
corpus therefore belongs inside whatever your platform already gives you: a container with a memory
limit and a job timeout. Running out of memory is reported against the case that ran out of it, and
costs that case's result rather than the whole run's — but it cannot be prevented from here.

**`--budget` bounds a solve, not a run.** It is per solve, and a case can route to several. Use
`--deadline` to bound the solving.

**`--deadline` bounds the solving, not everything the run does.** Its clock starts once discovery
has finished, and discovery is not free — it parses every case and its transitive `#include`s. It
also stops elenctic *starting* a case rather than interrupting one under way, so a solve already
running finishes on its own `--budget`.

**An enumerating solve holds at most a million answer sets.** Past that the search stops, and every
check whose reading ranges over the whole collection is `UNDECIDED` — a census of part of a
collection is not the census. The bound is fixed and has no flag: a case that meets it is asking for
a reading nobody can hold, and the encoding is where that is fixed. **Consequence runs are not
affected**, because clingo hands those back a refining sequence of consequence sets rather than a
stream of models, and only the latest is kept — nothing accumulates to bound. The **optimal-class
enumeration is a stream of models like any other** and meets the same bound: an optimal class of
more than a million members is truncated exactly as `AS(P)` is, and every optimal-base tag reading
over it is then `UNDECIDED`.

