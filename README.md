# elenctic

Test, debug and analyse answer set programs. Contracts are written in the program's own
comments; the library is first and the command line is a thin client over it.

```
$ elenctic drinks.lp
drinks.lp — FAIL
  [FAIL] @cautious { tea } (line 12): { tea } ⊆ ⋂ AS(P) = { biscuit } (missing: { tea })

0/1 passed, 1 fail
```

This is the successor to elenctic 0.3; see `DESIGN-2026-10-30.md` for the design and its open
items.

## Install

```
uv tool install .            # or: pixi install
uv tool install '.[theory]'  # with clingcon; pixi: pixi install -e theory
```

Python 3.14 and clingo 5.8 are required; clingcon 5.2 only for contracts that declare
`% @elenctic solver clingcon`, which are otherwise reported as an error.

## Use

```python
from elenctic import Limits, Program, check

report = check(Program.read("drinks.lp"), limits=Limits(seconds=10))
```

`check` returns a `Report` (a verdict per claim), a `Fault` (the question could not be asked), or
`None` (the file states no contract). Nothing is printed, nothing is global.

The claims, with the real output of each, are in `docs/reference/examples.md`.
Start with `docs/`: a tutorial, how-to guides, a reference, and an explanation of the semantics.

## Develop

```
uv sync --extra theory   # or: pixi install -e theory
./check.sh        # format, lint, strict types, tests
```

MIT licensed.
