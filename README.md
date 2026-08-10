# elenctic

[![CI](https://github.com/GregoryGelfond/elenctic/actions/workflows/ci.yml/badge.svg)](https://github.com/GregoryGelfond/elenctic/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Python](https://img.shields.io/badge/Python-%E2%89%A5%203.14-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

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
program is satisfiable, has exactly **2** answer sets, has `biscuit` in **every** one (cautious),
and has `tea` and `coffee` each in **some** one (brave — read severally, not jointly). Run it:

```console
$ elenctic run encodings/drinks/

1/1 passed
```

When a contract is wrong — say you claim `@cautious { tea }`, but `tea` is only in one menu —
elenctic tells you what it expected, what the program actually does, and the line of the claim it
judged, and exits non-zero:

```console
$ elenctic run encodings/drinks/
encodings/drinks/drinks.lp [clingo] — FAIL
  [FAIL] @cautious { tea } (line 10): { tea } ⊄ ⋂ AS(P) (observed { biscuit }; missing { tea })

0/1 passed
```

## Installation

elenctic is installed from git; it is not published to PyPI. It runs on **Python ≥ 3.14** (a
deliberate floor: the implementation uses modern Python idioms) and needs **clingo**, plus
**clingcon** for the theory fragment (`@assign` and CSP `@count`). Both solvers are on conda-forge
*and* on PyPI.

### In a [pixi](https://pixi.sh) project (recommended)

Take the solvers from conda-forge and elenctic from its repo. clingo (and clingcon) satisfy
elenctic's runtime imports, so the `[theory]` extra is not needed:

```toml
[dependencies]
clingo = "5.8.*"
clingcon = "5.2.1.*"   # only for the theory fragment

[pypi-dependencies]
elenctic = { git = "https://github.com/GregoryGelfond/elenctic.git" }
# pin a release for reproducibility, e.g. { git = "...", tag = "v0.3.0" }
```

Then `pixi run elenctic run PATH` runs a corpus of contracts.

### With pip

clingo ships 3.14 wheels; clingcon may build from source on 3.14.

```console
$ pip install "git+https://github.com/GregoryGelfond/elenctic.git"                    # answer-set fragment
$ pip install "elenctic[theory] @ git+https://github.com/GregoryGelfond/elenctic.git" # + clingcon
```

## The three-valued query

The tags above ask about a program's *consequences* — what holds in every answer set, what holds in
some, how many there are. `@query` asks a different question, Gelfond's three-valued epistemic
query: *what answer does the program give to a goal?* The answer is **yes**, **no**, or **unknown**.

Birds fly by default, but penguins, more specifically, do not. Sam is a (non-penguin) bird, Tweety
is a penguin, and Opus is a bird flagged as *abnormal* — so the default cannot be applied to him:

```asp
% encodings/birds/birds.lp
bird(sam).  bird(tweety).  penguin(tweety).  bird(opus).  ab(opus).

fly(X)  :- bird(X), not ab(X), not -fly(X).   % birds fly by default (unless abnormal) ...
-fly(X) :- penguin(X).                        % ... but penguins, specifically, do not

#show fly/1.
#show -fly/1.

% @expect        sat
% @query yes     { fly(sam) }
% @query no      { fly(tweety) }
% @query unknown { fly(opus) }
```

Does Sam fly? **yes** — the default applies. Does Tweety fly? **no** — the specific penguin rule
overrides the default. Does Opus fly? **unknown** — the default is blocked, but nothing settles the
matter either way. That `unknown` is the point of `@query`: it is exactly what the consequence
vocabulary (`@cautious` / `@brave`) cannot express. And the `no` is *known* falsity, not a mere
failure to derive — it holds because the program entails the **contrary** `-fly(tweety)`.

## What it gives you over hand-written solver calls

1. A **declarative contract language** in the program file itself — no hand-wired solver invocations.
2. **Reasoning-mode contracts** (brave/credulous, cautious/skeptical, witness, count, optimal) over
   the **observable**, including the three-valued **Gelfond query** `@query`.
3. A **three-valued verdict** (`PASS` / `FAIL` / `UNDECIDED`) that models a timeout as a
   first-class, non-failure outcome (a couldn't-decide is never dressed as a wrong answer).
4. **Multi-solver** support, including the theory solver clingcon, and **convention-driven
   discovery** of a corpus.

## Documentation

| | |
|---|---|
| [The contract language](docs/contract-language.md) | Every tag, what it claims, and what makes a contract well-formed. Read this to write contracts. |
| [Running a corpus](docs/running.md) | Discovery, the command line, the two streams, `--strict`, the verdict and the error loci, and what the bounds actually bound. |
| [The machine-readable report](docs/machine-readable-output.md) | `--format json`: the document's shape, the three registers, and what you may rely on across versions. |
| [Using elenctic as a library](docs/library-api.md) | Embedding elenctic in a runner of your own, without shelling out and parsing prose. |

## A worked corpus

[kr-domains](https://github.com/GregoryGelfond/kr-domains) puts elenctic to work on a broad set of
real encodings: shortest paths, the travelling salesman, task allocation, the equality-generalized
TSP, n-queens, send-more-money, and task scheduling, with **135 contract-checked cases** across
clingo and clingcon. It is a literate ASP corpus written to be read, and elenctic's first consumer:
each scenario `#include`s its domain encoding and declares its solver, and the whole corpus runs
directly under `elenctic`. It is the place to see the `@`-tags, the declared-solver model, and the
clingo / clingcon pairings used at scale.

## Running an untrusted corpus

elenctic runs the programs it is given, so a corpus is as trusted as code you would run. It is built
to be well-behaved about that — a case may only `#include` files from inside the corpus it belongs
to, text from a case cannot rewrite the report it appears in, and one unusable file costs its own
result and no other's. What that does and does not defend against is in
[SECURITY.md](SECURITY.md), along with how to report a vulnerability.

## Contributing

Bugs, questions and patches are all welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for how to get
set up, what the gate holds you to, and the conventions a patch is read against.

```console
$ git clone https://github.com/GregoryGelfond/elenctic
$ cd elenctic && pixi install
$ pixi run check        # ruff + mypy --strict + pytest
```

## License

MIT — see [LICENSE](LICENSE).
