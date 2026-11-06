# elenctic

Test, debug and analyze answer set programs. Contracts are written in the program's own
comments; the library is first and the command line is a thin client over it.

```
$ elenctic drinks.lp
drinks.lp — FAIL
  [FAIL] @cautious { tea } (line 12): { tea } ⊆ ⋂ AS(P) = { biscuit } (missing: { tea })

0/1 passed, 1 fail
```

This is the successor to elenctic 0.3.

## Install

```
uv tool install .            # or: pixi install
uv tool install '.[theory]'  # with clingcon; pixi: pixi install -e theory
```

Container recipe (`Containerfile`): build locally, then run — `docker build -f Containerfile -t elenctic .` then `docker run --rm -v "$PWD":/work:ro elenctic [elenctic arguments]`. No published image; no CI build.

Python 3.14 and clingo 5.8 are required; clingcon 5.2 only for contracts that declare
`% @elenctic solver clingcon`, which are otherwise reported as an error.

## Use

```python
from elenctic import Limits, Program, check

report = check(Program.read("drinks.lp"), limits=Limits(max_seconds=10))
```

`check` returns a `Report` (a verdict per claim), a `Fault` (the question could not be asked), or
`None` (the file states no contract). Nothing is printed, nothing is global.

The claims, with the real output of each, are in `docs/reference/examples.md`.
Start with `docs/`: a tutorial, how-to guides, a reference, and an explanation of the semantics.

## Develop

```
pixi install -e theory
pixi run -e theory check   # format, lint, strict types, import contracts, tests
pixi run -e py314 test     # or -e py315; same suite under that Python
```

`pixi run check` is the one gate; `./check.sh` runs it. `uv.lock` is tracked so that
`uv sync --locked` reproduces the same dependencies, which CI checks on Python 3.14 and 3.15.

Prose and identifiers use American spelling (`color`, `analyze`, `license`). A reading is
named for its tag's verb (`Asks`, `Binds`, …). Free functions are verbs; a method that
returns a changed copy is a verb too (`apply`, `rename`).

MIT licensed.
