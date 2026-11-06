# elenctic

[![CI](https://github.com/GregoryGelfond/elenctic-exp/actions/workflows/ci.yml/badge.svg)](https://github.com/GregoryGelfond/elenctic-exp/actions/workflows/ci.yml)
[![Python 3.14 | 3.15](https://img.shields.io/badge/python-3.14%20%7C%203.15-blue)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Pixi](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/prefix-dev/pixi/main/assets/badge/v0.json)](https://pixi.sh)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
<!-- TODO(release): add once 1.0.0 is published.
[![PyPI](https://img.shields.io/pypi/v/elenctic)](https://pypi.org/project/elenctic/)
[![conda-forge](https://img.shields.io/conda/vn/conda-forge/elenctic)](https://anaconda.org/conda-forge/elenctic)
-->

A testing and analysis library for answer set programs, with a thin CLI. Claims about a program
live in its own comments (`@expect`, `@count`, `@answer-set`, `@cautious`, `@brave`, `@query`,
`@cost`) and are checked under clingo or clingcon.

*Elenctic*, from Greek ἐλεγκτικός (ἔλεγχος, *elenchos*), "serving to refute by
cross-examination": the Socratic elenchus. A contract is a thesis about the program; `FAIL` is
its refutation, and `UNDECIDED` is aporia, an honest "cannot say" rather than a false "no".

Status: pre-1.0.

## Install

Requires Python 3.14+ and clingo 5.8. The optional `theory` extra pulls in clingcon 5.2 for
contracts that declare `% @elenctic solver clingcon`.

<!-- TODO(release): the PyPI and conda-forge lines apply once 1.0.0 is published. -->

```bash
# pip
pip install elenctic
pip install 'elenctic[theory]'

# uv — as a project dependency, or as a tool on PATH
uv add elenctic
uv add 'elenctic[theory]'
uv tool install elenctic
uv tool install 'elenctic[theory]'

# pixi — from conda-forge once the feedstock exists, or from PyPI
pixi add elenctic
pixi add --pypi elenctic
pixi add --pypi 'elenctic[theory]'

# conda / mamba (conda-forge)
conda install -c conda-forge elenctic
mamba install -c conda-forge elenctic
```

From source, straight from Git or from a clone:

```bash
pip install 'elenctic[theory] @ git+https://github.com/GregoryGelfond/elenctic-exp'

git clone https://github.com/GregoryGelfond/elenctic-exp && cd elenctic-exp
pip install '.[theory]'
uv tool install '.[theory]'
pixi install -e theory     # the locked environment
```

### Container

No prebuilt image is published. The `Containerfile` is a local recipe: build it yourself with
Docker or Podman, then mount a directory of `.lp` files and run a check.

```bash
docker build -f Containerfile -t elenctic .
podman build -f Containerfile -t elenctic .

docker run --rm -v "$PWD":/work:ro elenctic drinks.lp
podman run --rm -v "$PWD":/work:ro elenctic drinks.lp
```

The image includes the `theory` extra (clingo and clingcon). The entrypoint is `elenctic`; pass
the same arguments you would on the host.

## Quick start

Save this as `drinks.lp`:

```
% @expect sat
% @count 2
% @brave { tea, coffee }
% @cautious { biscuit }
% @query unknown { tea }
{ tea; coffee } = 1.
biscuit.
#show tea/0.
#show coffee/0.
#show biscuit/0.
```

```bash
$ elenctic drinks.lp
1/1 passed
```

Change `@count 2` to `@count 3` and run again:

```bash
$ elenctic drinks.lp
drinks.lp — FAIL
  [FAIL] @count 3 (line 2): 3 expected, 2 distinct shown answer sets

0/1 passed, 1 fail
```

`elenctic PATH…` is `elenctic test PATH…`. From Python the same check is silent and returns a
value:

```python
from elenctic import Limits, Program, check

report = check(Program.read("drinks.lp"), limits=Limits(max_seconds=10))
```

## Usage

| | |
|---|---|
| `elenctic [test] PATH…` | check programs against their contracts ([reference](docs/reference/reference.md#command-line)) |
| `--format full\|short\|json` | rustc multi-line diagnostics (default), one-line short, or JSON ([output](docs/reference/reference.md#output), [diagnostics](docs/reference/reference.md#diagnostics)) |
| Exit `0` / `1` / `2` / `3` | claims hold, claim unmet, fault, internal error ([exit codes](docs/reference/reference.md#exit-codes)) |

Claims with real command output: [docs/reference/examples.md](docs/reference/examples.md).
Tutorial: [docs/tutorial/first-contract.md](docs/tutorial/first-contract.md). Full map:
[docs/index.md](docs/index.md).

## Develop

```bash
pixi install -e theory
pixi run -e theory check   # format, lint, strict types, import contracts, tests
pixi run -e py314 test     # or -e py315
```

`pixi run check` is the one gate; `./check.sh` runs it. `uv.lock` is tracked so
`uv sync --locked` reproduces the same dependencies.

## License

Licensed under the [MIT license](LICENSE). Changes are in the [changelog](CHANGELOG.md).
