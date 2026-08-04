# elenctic

A declarative testing framework for Answer Set Programming.

**Answer Set Programming (ASP)** is a declarative approach to knowledge representation and
combinatorial search: you write a logic program (facts, rules, and constraints), and a solver
computes its **answer sets** — the stable models that are its solutions. ASP is well suited to
planning, configuration, diagnosis, and default and commonsense reasoning;
[clingo](https://potassco.org) is the dominant solver, with clingcon extending it to constraints
over integers.

**Who it's for.** If you write and maintain ASP encodings (in clingo or clingcon) and want to keep
them correct as they evolve, elenctic is your test harness — what pytest is to Python, but speaking
ASP's own reasoning modes: what holds in *every* answer set (cautious) or in *some* (brave), what is
*optimal*, how *many* solutions there are, and what the program *answers* to a three-valued query
(yes / no / unknown, where "unknown" is a genuine third value, never a guess).

You state the expected behaviour as **in-file `@`-annotations** (a contract) in the `.lp` file
itself, and elenctic checks it. The contract language is **language-parametric**: it describes the
program's *observable behaviour* (its shown atoms and theory output) under a **declared solver**
(default `clingo`; `clingcon` for integer-constraint theories), not any solver's internals. A
theory-free claim carries across Potassco engines, which agree on the theory-free reduct; a
theory-specific tag (such as `@assign`) holds only under a solver that provides that theory. This
package is its **reference implementation**, over the clingo / clingcon Python API.

## The name

*Elenctic* (from Greek ἔλεγχος, *elenchos*, via the adjective ἐλεγκτικός) means "serving to refute,
by cross-examination" — the **Socratic elenchus**, the method of testing a claim by questioning it
until it survives or is shown false. A test harness does exactly that: it cross-examines a program
against a claimed expectation (the contract) and reports the result.

The fit reaches the design. The contract is a *thesis* about the program; a `FAIL` is a refutation —
the program entails the contrary of what was claimed; and an `UNDECIDED` is Socratic *aporia*, the
honest "we cannot say," never collapsed into a false "no." The three-valued verdict is the elenchus'
own register: a claim upheld, refuted, or left open.

## A first example

Put a program and its contract in one `.lp` file:

```asp
% encodings/drinks/drinks.lp
1 { tea; coffee } 1.        % exactly one drink
biscuit.                    % always a biscuit
#show tea/0.
#show coffee/0.
#show biscuit/0.

% @expect   sat
% @count    2
% @cautious { biscuit }
% @brave    { tea, coffee }
```

The two answer sets are `{tea, biscuit}` and `{coffee, biscuit}`. The contract states that the
program is satisfiable, has exactly **2** answer sets, has `biscuit` in **every** one (cautious), and
has `tea` and `coffee` each in **some** one (brave — read severally, not jointly). Run it:

```console
$ elenctic encodings/
1/1 passed
```

`--explain` shows how each tag is routed to a solver run and the fields it reads, *without
solving*, and whether that run collapses its answer sets onto the shown atoms — which is what
`projects` reports. It is `yes` only under a theory solver, since that is the only place the
collapse can lose anything; a plain clingo run is `no` because there is nothing behind the shown
view to lose, not because a projection was declined. This contract needs three runs (a full
enumeration for `@count`, and the native cautious and brave runs):

```console
$ elenctic encodings/ --explain
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

When a contract is wrong — say you claim `@cautious { tea }`, but `tea` is only in one menu —
elenctic tells you what it expected, what the program actually does, and the line of the claim it
judged, and exits non-zero:

```console
$ elenctic encodings/
encodings/drinks/drinks.lp [clingo] — FAIL
  [FAIL] @cautious { tea } (line 10): { tea } ⊄ ⋂ AS(P) = { biscuit } (missing: { tea })

0/1 passed
```

Claims that failed for the *same* reason share a row rather than repeating it. Three `@cautious`
lines against a program with no answer set are one fact about three claims, so it is stated once
and the claims follow it:

```console
  [FAIL] @cautious: no cautious consequences — AS(P) = ∅
         applied to { tea } (line 10), { coffee } (line 11), { biscuit } (line 12)
```

## Querying a program with `@query`

The modes above ask about a program's *consequences*. `@query` asks a different question — Gelfond's
three-valued epistemic query: *what answer does the program give to a goal?* — and the answer is
**yes**, **no**, or **unknown**.

Here is the classic Tweety example in miniature (the full Gelfond & Kahl §5.4.3 program is in the test
suite): birds fly by default, but penguins, more specifically, do not. Sam is a (non-penguin) bird,
Tweety is a penguin, and Opus is a bird flagged as *abnormal* (say, possibly wounded), so the default
cannot be applied to him.

```asp
% encodings/birds/birds.lp
bird(sam).
bird(tweety).
penguin(tweety).
bird(opus).
ab(opus).                              % opus is an abnormal bird (e.g. possibly wounded)

fly(X)  :- bird(X), not ab(X), not -fly(X).   % birds fly by default (unless abnormal) ...
-fly(X) :- penguin(X).                         % ... but penguins, specifically, do not

#show fly/1.
#show -fly/1.

% @expect        sat
% @query yes     { fly(sam) }
% @query no      { fly(tweety) }
% @query unknown { fly(opus) }
```

The single answer set is `{ fly(sam), -fly(tweety) }` — note it contains *neither* `fly(opus)` nor
`-fly(opus)`. So all three questions hold, and elenctic confirms it:

```console
$ elenctic encodings/
1/1 passed
```

Does Sam fly? **yes** — the default applies. Does Tweety fly? **no** — the specific penguin rule
overrides the default. Does Opus fly? **unknown** — the default is blocked (he is abnormal), but
nothing settles the matter either way. That `unknown` is the point of `@query`: it is exactly what
the consequence vocabulary (`@cautious`/`@brave`) cannot express. And the `no` is *known* falsity, not
a mere failure to derive — it holds because the program entails the **contrary** `-fly(tweety)`, which
is why the encoding must `#show` `-fly`.

## What it gives you over hand-written solver calls

1. A **declarative contract language** in the program file itself — no hand-wired solver invocations.
2. **Reasoning-mode contracts** (brave/credulous, cautious/skeptical, witness, count, optimal) over
   the **observable**, including the three-valued **Gelfond query** `@query`.
3. A **three-valued verdict** (`PASS` / `FAIL` / `UNDECIDED`) that models a timeout as a
   first-class, non-failure outcome (a couldn't-decide is never dressed as a wrong answer).
4. **Multi-solver** support, including the theory solver clingcon, and **convention-driven
   discovery** of a corpus.

## The contract

A **contract block** is a run of `%`-comment lines `% @<tag> …`. Every model-bearing tag ranges over
the **observable**.

### Governing principles

**The observable.** A contract may speak only of what the program makes observable: the projection of
an answer set onto its `#show`-declared predicates, plus the theory (CSP) assignment when a theory is
in force. Hidden atoms are not checkable. A **strong-negation literal** `-a` is a *distinct* atom from
`a`, observable only if the program shows it on the same footing.

**The base.** A model-base tag is evaluated over a chosen set of answer sets. Writing `optimal`
before the payload chooses the optimal class `Opt(P)`; writing nothing chooses every answer set
`AS(P)`, which is what the tables below mean by a base of `all`. So `@cautious optimal { L }` reads
"`L` holds in every optimal model." The default has a name so that it can be talked about, but it
has no spelling: `optimal` is the only qualifier a contract may write, and `@cautious all { L }` is
a contract error.

### Grammar

| tag | meaning (over the observable; base defaults to `all`) |
|---|---|
| `@expect sat \| unsat` | the program has at least one answer set / none |
| `@model [optimal] { L }` | some (optimal) answer set's shown projection equals `L` |
| `@cautious [optimal] { L }` | each literal in `L` holds in **every** (optimal) answer set (⋂) |
| `@brave [optimal] { L }` | each literal in `L` holds in **some** (optimal) answer set (⋃) — severally, not jointly |
| `@count [optimal] n` | exactly `n` distinct (optimal) observables |
| `@cost { c }` | the proven optimal cost vector (priority-ordered) is `c` |
| `@optimal { L }` | sugar for `@model optimal { L }` |
| `@assign [optimal] { v=k, … }` | some (optimal) answer set's theory assignment includes `v=k, …` (clingcon) |
| `@model [optimal] { L } where { A }` | one (optimal) answer set has shown projection `L` **and** assignment ⊇ `A` (jointly, on the same model; clingcon) |
| `@query A { Q }` | the answer to the query `Q` is `A ∈ {yes, no, unknown}` (Gelfond Def 2.2.2) |
| `@query A { q(X̄) } = { B }` | the bindings yielding answer `A` are exactly `B` |
| `@note …` | free prose, surfaced in the diagnostic |

**Which tags may be written more than once.** `@cautious`, `@brave`, their two `optimal` siblings,
and `@query` may each appear on several lines of one contract; `@note` may too. Each writing is an
**independent claim**, with its own verdict, its own diagnostic and its own line — writing
`@cautious { a }` and `@cautious { b }` on two lines says exactly what `@cautious { a, b }` says on
one, but a failure names the line whose claim was false rather than the union.

Every other tag may appear at most once **per `(mode, base)` cell**, which is not the same as at
most once: `@model`, `@count` and `@assign` each have an `all` cell and an `optimal` cell, so
`@count 12` and `@count optimal 3` may be written together (and are then cross-checked, since an
optimal class cannot be larger than the whole). `@optimal { L }` is sugar for `@model optimal { L }`
and shares its cell. Only `@expect` and `@cost` are one to a contract outright.

A litset `{ … }` is comma-separated and paren-aware (an atom may contain commas, e.g.
`included(s,a,2,1)`), and may span continuation `%` lines while a brace stays open. An `@`-tag's
payload runs to the end of its line, so write explanatory comments on their own lines (a `%%` or `%`
line), not after the payload — `% @count 2  % two answer sets` would read the comment as part of the
count. (Inline-comment support after a payload is a planned convenience.)

### The three-valued query

`@query` is Gelfond's epistemic query, faithfully: it asks *what answer the program gives*, and the
answer is three-valued. **yes** if the (conjunctive) query is true in every answer set; **no** if it
is false in every answer set (some conjunct's *contrary* present in each — a "no" needs the contrary
shown, never mere failure-to-derive); **unknown** otherwise — the entertained-but-unsettled middle
that classical logic cannot name. (See the worked examples below.)

### Well-formedness

`parse` accepts exactly the well-formed blocks and **rejects every other with a diagnostic** — it
never silently defaults. Exactly one `@expect`; single-valued witness/scalar tags per `(mode, base)`
cell; `@count 0 ⟺ @expect unsat`; and the precondition tags (`@cost`/`optimal` need an optimizing
encoding; `@assign`, `@assign optimal`, and a `where`-witness need clingcon; a `no`/`unknown`
`@query` needs the contrary `#show`n) are checked at discovery against the actual encoding.

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
reported loudly and distinctly rather than as a costumed `FAIL`. They divide by whose fault they
are: a bad contract (`ContractError`), a mis-shaped corpus or a missing declared solver
(`DiscoveryError`), or a program that cannot be run at all — one that will not ground, or whose
`#include` does not resolve (`ProgramError`) — are yours to fix; an `elenctic` bug
(`HarnessError`) is ours. Two more are yours to fix and are named for where the fault lies rather
than for an exception, because neither is one this package defines: a case the run's `--deadline`
never reached, and a case that ran out of memory. A case that cannot be run does not stop the
others: it is reported on its own and the rest of the corpus still runs.

## Worked examples

UNSAT, with a documenting note:

```asp
% @expect unsat
% @note   the budget cap excludes every s–t path
```

Optimization — the proven optimal cost, and one optimal model (a shortest path under an edge budget):

```asp
% @expect  sat
% @cost    { 4 2 }
% @optimal { included(s,a,2,1), included(a,t,2,1), start(s), end(t) }
% @note    the budget rules out the direct edge; the two-hop detour is optimal
```

A unique, counted, CSP-only solution (the answer lives entirely in the theory assignment):

```asp
% @expect sat
% @count  1
% @assign { digit(s)=9, digit(e)=5, digit(n)=6, digit(d)=7,
%           digit(m)=1, digit(o)=0, digit(r)=8, digit(y)=2 }
```

The three-valued query, on Gelfond & Kahl's *cowardly students* (§5.1.2; an encoding that shows the
relevant strong-negation literals, so a "no" means *known* false, not merely underived):

```asp
% @expect    sat
% @query yes     { afraid(john,math) }
% @query no      { afraid(mary,math) }
% @query unknown { afraid(bob,math) }
```

John (English) is afraid of math by default; Mary is a stated strong exception (known *not* afraid);
Bob, in CS, is genuinely undetermined — the **unknown** that the consequence vocabulary cannot name.

## A worked corpus

[kr-domains](https://github.com/GregoryGelfond/kr-domains) puts elenctic to work on a broad set of
real encodings: shortest paths, the travelling salesman, task allocation, the equality-generalized
TSP, n-queens, send-more-money, and task scheduling, with **135 contract-checked cases** across
clingo and clingcon. It is a literate ASP corpus written to be read, and elenctic's first consumer:
each
scenario `#include`s its domain encoding and declares its solver, and the whole corpus runs directly
under `elenctic`. It is the place to see the `@`-tags, the declared-solver model, and the
clingo / clingcon pairings used at scale.

## Running

The standalone runner discovers cases under a target (a single `.lp` file or a directory) and runs them:

```console
$ elenctic [target]            # default target tests/; `elenctic --help` lists the exit statuses
$ elenctic tests/feasible.lp   # run a single case file
$ elenctic tests/ --explain    # narrate the derived run plan, without solving
$ elenctic tests/ --strict     # fail the run on any corpus-hygiene issue (the CI gate)
$ elenctic tests/ --budget 60      # per-solve time limit (default 30s)
$ elenctic tests/ --deadline 600   # once solving has run 10 minutes, start no more cases; those not reached are reported as not run
$ elenctic tests/ --format json    # the machine-readable report (below)
$ elenctic --print-schema          # the JSON schema of that report, without running anything
```

`--budget` and `--deadline` each take a **positive finite** number of seconds. A run that wants no
practical per-solve limit asks for a large number; a run that wants no deadline leaves `--deadline`
off, which is the default.

### Machine-readable output

`--format json` writes the whole run as **one JSON object on standard output**, and moves everything
else — the per-case report, the hygiene summary, every diagnostic — to standard error. Standard
output carries a whole document or nothing at all, so a consumer can parse it without filtering.
Running a single case file:

```console
$ elenctic menu.lp --format json
{
  "schema_version": 1,
  "invocation": { "target": "menu.lp", "strict": false, "budget": 30.0, "deadline": null },
  "summary": { "total": 1, "passed": 0, "failed": 1, "undecided": 0, "errors": 0, "hygiene": 0 },
  "cases": [
    {
      "source": "menu.lp",
      "solver": "clingo",
      "verdict": "fail",
      "checks": [
        {
          "tag": "@cautious",
          "subject": "{ tea }",
          "status": "fail",
          "message": "{ tea } ⊄ ⋂ AS(P) = { } (missing: { tea })",
          "line": 3,
          "conclusion": "exhausted"
        },
        {
          "tag": "@expect sat",
          "subject": "",
          "status": "pass",
          "message": "AS(P) ≠ ∅ — a model exists",
          "line": 2,
          "conclusion": "incomplete"
        }
      ]
    }
  ],
  "errors": [],
  "hygiene": []
}
```

(`invocation`, `summary` and each check are shown on one line here for brevity; the real output is
indented throughout.)

**Three registers, and confusing them is the one mistake worth guarding against.** A case in `cases`
received a judgment about the program under test. An entry in `errors` says *no* judgment could be
made, and why — usually not a fault in the contract at all. An entry in `hygiene` is an observation
about the corpus's own health and is neither. Draw a failure indicator for a non-passing case; never
for an error.

**The exit status is readable off the document alone**, in this order: `3` if any error has
`is_elenctic_bug` true; otherwise `2` if there is any error at all, or any observation graded
`error`; otherwise `1` if any case's verdict is not `pass`; otherwise `0`.

**Each check carries the line its claim was written on**, 1-based, so a result can be placed where
the claim is rather than against the file. `conclusion` says how the search behind the verdict ended,
which is what tells "the budget was too small" apart from "the program is wrong".

**Three tiers of change, so you know what you may rely on.** `schema_version` changes when a field is
added or removed, or when one of the closed enumerations (`verdict`, `status`, `conclusion`, `scope`,
`grade`) gains a member. The open-valued string fields — `kind`, `solver`, and a check's `tag` — may
gain values *without* a version bump, so treat an unfamiliar one as a value rather than an error.
Every `message` is **opaque**: display it, do not parse it, and expect its wording to change.

Paths in the document follow the target as you named it, so a relative target yields relative paths;
resolve them against the directory you ran from, which the document does not record.

`elenctic --print-schema` writes the JSON Schema of this document and exits, without looking for a
corpus. Three things are refused rather than guessed at: a `--format` this version does not know;
`--explain --format json` (a dry run narrates a plan, and this version describes no document for
one); and a `--budget` or `--deadline` that is not a positive finite number of seconds. A refused
command line produces **no** document, so
check the exit status before parsing — and note that `--print-schema` puts the *schema* on that
stream, which parses as JSON and has none of the fields above.

Redirecting standard error onto standard output (`--format json 2>&1`) gives away the guarantee by
your own hand.

### The corpus is code you run

elenctic runs the programs it is given, so a corpus is as trusted as code you would run. It is
built to be well-behaved about that — a case may only `#include` files from inside the corpus it
belongs to; text from a case cannot rewrite the report it appears in; and one unusable file costs
its own result and no other's — but two limits are worth stating plainly rather than leaving to be
discovered.

**`--budget` bounds a solve, not a run.** It is per solve, and a case can route to several. Use
`--deadline` to bound the solving.

**`--deadline` bounds the solving, not everything the run does.** Its clock starts once discovery
has finished, and discovery is not free — it parses every case and its transitive `#include`s. It
also stops elenctic *starting* a case rather than interrupting one under way, so a solve already
running finishes on its own `--budget`.

**Grounding is not bounded at all.** A program can be small and still ground to something enormous,
and clingo offers no way to cap that — it is not a limit elenctic can lift. Running an untrusted
corpus therefore belongs inside whatever your platform already gives you: a container with a memory
limit and a job timeout. Running out of memory is reported against the case that ran out of it, and
costs that case's result rather than the whole run's — but it cannot be prevented from here.

**An enumerating solve holds at most a million answer sets.** Past that the search stops, and every
check whose reading ranges over the whole collection is `UNDECIDED` — a census of part of a
collection is not the census. The bound is fixed and has no flag: a case that meets it is asking for
a reading nobody can hold, and the encoding is where that is fixed. **Consequence runs are not
affected**, because clingo hands those back a refining sequence of consequence sets rather than a
stream of models, and only the latest is kept — nothing accumulates to bound. The **optimal-class
enumeration is a stream of models like any other** and meets the same bound: an optimal class of
more than a million members is truncated exactly as `AS(P)` is, and every optimal-base tag reading
over it is then `UNDECIDED`.

Each pipeline stage is also runnable for inspection: `python -m elenctic.expectation <file.lp>`
(the parsed contract), `python -m elenctic.run <file.lp>` (the derived run plan),
`python -m elenctic.discovery <file-or-dir>` (the discovered cases), and
`python -m elenctic.solvers <MODE> <file.lp>` (one solve's outcome, with clingo).

Beyond the CLI, elenctic is also a **library**: `discover(target)` yields cases, `run_case(case)`
yields the per-check reports, `case_verdict(reports)` folds them, and `render(case, reports)` formats
the diagnostic — ready to drive `pytest.mark.parametrize` when you want elenctic's results inside
another test runner.

## Discovery

Discovery is **content-keyed**: a `.lp` file is a *case* iff it carries a contract (any known
`@`-tag), otherwise it is a *library* (an `#include` target, never run directly). A directory is
walked for contract-bearing files; a single file is run directly. The program under test is the case
file plus its resolved `#include`s, and the solver is **declared** in the contract
(`% @elenctic solver clingcon`, default `clingo`), never inferred from a filename. An undeclared
theory program is a loud error: elenctic never silently mis-solves a theory program under plain clingo.

## Installation

elenctic runs on **Python ≥ 3.14** (a deliberate floor: the implementation uses modern Python
idioms) and needs **clingo**, plus **clingcon** for the theory fragment (`@assign` and CSP `@count`).
Both solvers are on conda-forge *and* on PyPI.

### In a [pixi](https://pixi.sh) project (recommended)

Take the solvers from conda-forge and elenctic from its repo. clingo (and clingcon) satisfy
elenctic's runtime imports, so the `[theory]` extra is not needed:

```toml
[dependencies]
clingo = "5.8.*"
clingcon = "5.2.1.*"   # only for the theory fragment

[pypi-dependencies]
elenctic = { git = "https://github.com/GregoryGelfond/elenctic.git" }
# pin a release for reproducibility, e.g. { git = "...", tag = "v0.2.0" }
```

Then `pixi run elenctic <path>` runs a corpus of contracts.

### With pip

clingo ships 3.14 wheels; clingcon may build from source on 3.14.

```console
$ pip install "git+https://github.com/GregoryGelfond/elenctic.git"                    # answer-set fragment
$ pip install "elenctic[theory] @ git+https://github.com/GregoryGelfond/elenctic.git" # + clingcon
```

### Working on elenctic

```console
$ git clone https://github.com/GregoryGelfond/elenctic
$ cd elenctic && pixi install
$ pixi run check        # ruff + mypy --strict + pytest
```

## License

MIT — see [LICENSE](LICENSE).
