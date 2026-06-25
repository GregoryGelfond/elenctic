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
itself, and elenctic checks it. The contract language is **language-neutral**: it describes the
program's *observable behaviour* (its shown atoms and theory output), not any solver's internals.
This package is its **reference implementation**, over the clingo / clingcon Python API.

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

`--explain` shows how each tag is routed to a solver run and the fields it reads, *without solving*,
and whether the run projects its census onto the shown atoms. This contract needs three runs (a full
enumeration for `@count`, and the native cautious and brave runs):

```console
$ elenctic encodings/ --explain
encodings/drinks/drinks.lp [clingo]
    ENUM_ALL (projects: no):
        @count — reads {full census}
        @expect sat — reads {—}
    CAUTIOUS_ALL (projects: no):
        @cautious — reads {cautious}
    BRAVE_ALL (projects: no):
        @brave — reads {brave}
```

When a contract is wrong — say you claim `@cautious { tea }`, but `tea` is only in one menu —
elenctic tells you what it expected and what the program actually does, and exits non-zero:

```console
$ elenctic encodings/
encodings/drinks/drinks.lp [clingo] — FAIL
  [FAIL] @cautious: { tea } ⊄ ⋂ AS(P) = { biscuit } (missing: { tea })

0/1 passed
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

**The base.** A model-base tag is evaluated over a chosen set of answer sets, named by an optional
base qualifier: `all` (the default — every answer set `AS(P)`) or `optimal` (the optimal class
`Opt(P)`). So `@cautious optimal { L }` reads "`L` holds in every optimal model."

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
- **FAIL** — the program decided *wrong* (the contract is violated by a completed solve).
- **UNDECIDED** — the solve was cut off by the time budget before deciding. A timeout is **never**
  `FAIL` and **never** `UNSAT`: "could not decide" and "decided wrong" are different facts. (This is
  also consequence-soundness: an interrupted brave/cautious run carries a one-sided error.)

A case passes iff every check passes. Errors are a separate register, never verdicts: a bad contract
(`ContractError`), a mis-shaped corpus (`DiscoveryError`), or an elenctic bug (`HarnessError`) is
reported loudly and distinctly, never as a costumed `FAIL`.

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

## Running

The standalone runner discovers cases under a target (a single `.lp` file or a directory) and runs them:

```console
$ elenctic [target]            # run every case under target (default: tests/); exit 0 pass, 1 fail/undecided, 2 error
$ elenctic tests/feasible.lp   # run a single case file
$ elenctic tests/ --explain    # narrate the derived run plan, without solving
```

Each pipeline stage is also runnable for inspection: `python -m elenctic.expectation <file.lp>`
(the parsed contract), `python -m elenctic.run <file.lp>` (the derived run plan),
`python -m elenctic.discovery <file-or-dir>` (the discovered cases), and
`python -m elenctic.solvers <MODE> <file.lp>` (one solve's outcome, with clingo).

A corpus consumes elenctic as a library: `discover(target)` yields cases, `run_case(case)` yields the
per-check reports, `case_verdict(reports)` folds them, and `render(case, reports)` formats the
diagnostic, ready to drive `pytest.mark.parametrize`.

## Discovery

Discovery is **content-keyed**: a `.lp` file is a *case* iff it carries a contract (any known
`@`-tag), otherwise it is a *library* (an `#include` target, never run directly). A directory is
walked for contract-bearing files; a single file is run directly. The program under test is the case
file plus its resolved `#include`s, and the solver is **declared** in the contract
(`% @elenctic solver clingcon`, default `clingo`), never inferred from a filename. An undeclared
theory program is a loud error: elenctic never silently mis-solves a theory program under plain clingo.

## Installation

elenctic runs on **Python ≥ 3.14** (a deliberate floor — the implementation uses modern Python
idioms) and needs **clingo**, plus **clingcon** for the theory fragment (`@assign` and CSP `@count`).
Both solvers are on conda-forge *and* on PyPI.

The development setup uses [pixi](https://pixi.sh), which also pins the solvers and runs the gate:

```console
$ git clone https://github.com/GregoryGelfond/elenctic
$ cd elenctic && pixi install
$ pixi run check        # ruff + mypy --strict + pytest
```

Or install with pip (clingo ships 3.14 wheels; clingcon may build from source on 3.14):

```console
$ pip install "git+https://github.com/GregoryGelfond/elenctic.git"                    # answer-set fragment
$ pip install "elenctic[theory] @ git+https://github.com/GregoryGelfond/elenctic.git" # + clingcon
```

## License

MIT — see [LICENSE](LICENSE).
