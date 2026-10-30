# elenctic

Check answer set programs against contracts written in their own comments.
A library first; the command line is a thin client over it.

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
uv tool install .          # or: pixi install
```

Python 3.14 and clingo 5.8 are required.

## Use

```python
from elenctic import Limits, Program, check

report = check(Program.read("drinks.lp"), limits=Limits(seconds=10))
```

`check` returns a `Report` (a verdict per claim), a `Fault` (the question could not be asked), or
`None` (the file states no contract). Nothing is printed, nothing is global.

Start with `docs/`: a tutorial, how-to guides, a reference, and an explanation of the semantics.

## Develop

```
./check.sh        # format, lint, strict types, tests
```

MIT licensed.
