# elenctic

A declarative testing framework for Answer Set Programming.

elenctic lets you state what an answer-set program *should* compute as **in-file `@`-annotations**
(a contract), and checks the program against it. The contract language is **language-neutral**: it
describes the program's *observable behaviour* (its shown atoms and theory output), not any solver's
internals. This package is the **reference implementation**, over the clingo / clingcon Python API.

```asp
% shortest-path/test-03.lp
% @expect  sat
% @cost    { 4 2 }
% @optimal { included(s,a,2,1), included(a,t,2,1), start(s), end(t) }
% @note    the budget rules out the direct edge; the two-hop detour is optimal
```

```console
$ elenctic encodings/ tests/cases/
98/98 passed
```

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
| `@assign { v=k, … }` | some answer set's theory assignment includes `v=k, …` (clingcon) |
| `@query A { Q }` | the answer to the query `Q` is `A ∈ {yes, no, unknown}` (Gelfond Def 2.2.2) |
| `@query A { q(X̄) } = { B }` | the bindings yielding answer `A` are exactly `B` |
| `@note …` | free prose, surfaced in the diagnostic |

A litset `{ … }` is comma-separated and paren-aware (an atom may contain commas, e.g.
`included(s,a,2,1)`), and may span continuation `%` lines while a brace stays open.

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
encoding, `@assign` needs clingcon, a `no`/`unknown` `@query` needs the contrary `#show`n) are
checked at discovery against the actual encoding.

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
% @query yes     { afraid(john,math) }   % an english student: the default holds
% @query no      { afraid(mary,math) }   % a stated strong exception: known not afraid
% @query unknown { afraid(bob,math) }    % a CS student: may or may not be — genuinely undetermined
```

## Running

The standalone runner discovers a corpus and runs it:

```console
$ elenctic <encodings_root> [cases_root]    # run every contract; exit 0 pass / 1 fail-or-undecided / 2 error
$ elenctic <encodings_root> --explain       # narrate the derived run plan, without solving
```

Each pipeline stage is also runnable for inspection: `python -m elenctic.expectation <file.lp>`
(the parsed contract), `python -m elenctic.run <file.lp>` (the derived run plan),
`python -m elenctic.discovery <encodings> [cases]` (the discovered cases), and
`python -m elenctic.solvers <MODE> <file.lp>` (one solve's outcome, with clingo).

A corpus consumes elenctic as a library: `discover(layout)` yields cases, `run_case(case)` yields the
per-check reports, `case_verdict(reports)` folds them, and `render(case, reports)` formats the
diagnostic — ready to drive `pytest.mark.parametrize`.

## Discovery

Discovery is convention-driven and parameterized entirely by a `Layout`, so it hard-codes nothing
about any corpus. Encodings live in `<encodings_root>/<domain>/`; instances in
`<cases_root>/<domain>/[variant-NN/]`. A filename ending `-clingcon` is the theory variant, else the
clingo baseline; each instance is paired with its applicable encoding(s), and a self-contained
encoding (no instances) carries its contract in its own header.

## Installation

elenctic runs on Python ≥ 3.14 and needs **clingo** (and **clingcon** for the theory fragment). Both
are on conda-forge; install the environment with `pixi install`, then `pixi run check` for the gate
(ruff, mypy --strict, pytest) or `pixi run test`.
