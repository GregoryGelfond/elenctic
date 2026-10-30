"""Run generated cases through elenctic 0.3 and this library; compare every claim's verdict.

python scripts/differential.py LEGACY_SRC [--cases N] [--seed S] [--optimize] [--hide-contraries]
"""

import argparse
import json
import random
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from elenctic.check import check
from elenctic.program import Fault, Program
from elenctic.verdicts import Report

LITERALS = ("a", "b", "c", "-a", "-b", "-c")
RULES = (
    "{a}.", "{b}.", "{c}.", "a.", "-b.", "a :- not b.", "b :- not a.", "-c :- a.", "c :- b.",
    ":- a, b.", ":- -c, c.", "{a; b; c} = 1.", "1 {b; c} 2.", "-a :- not a, c.", "c :- not -c, b.",
)  # fmt: skip
SHOW = "#show a/0. #show b/0. #show c/0. #show -a/0. #show -b/0. #show -c/0.\n"
SHOWN_POSITIVE = "#show a/0. #show b/0. #show c/0.\n"
OBJECTIVES = (
    ("#minimize { 1,a : a; 2,b : b; 1,c : c }.", 1),
    ("#maximize { 2,a : a; 1,b : b; 1,c : c }.", 1),
    ("#minimize { 1@2,a : a; 1@1,b : b }.", 2),
    ("#maximize { 1@2,a : a; 1@1,c : c }. #minimize { 1@1,b : b }.", 2),
    (":~ c. [2@1]", 1),
)
OPTIMAL_TAGS = ("@cautious optimal", "@brave optimal", "@model optimal")
CELL_TAGS = ("@cautious", "@brave", "@model")
QUERY_TAGS = ("@query yes", "@query no", "@query unknown")


def _set(rng: random.Random) -> str:
    return "{ " + ", ".join(rng.sample(LITERALS, rng.choice((1, 1, 2)))) + " }"


def _optimal_claims(rng: random.Random, levels: int) -> Iterator[str]:
    if rng.random() < 0.5:
        yield f"% @count optimal {rng.randrange(1, 4)}"
    if rng.random() < 0.5:
        yield "% @cost { " + " ".join(str(rng.randrange(-4, 3)) for _ in range(levels)) + " }"
    for tag in rng.sample(OPTIMAL_TAGS, rng.randrange(1, 4)):
        spelled = "@optimal" if tag == "@model optimal" and rng.random() < 0.5 else tag
        yield f"% {spelled} {_set(rng)}"


def _claims(rng: random.Random, levels: int) -> Iterator[str]:
    if rng.random() < 0.2:
        yield "% @expect unsat"
        yield from rng.sample(["", "% @count 0"], 1)
        return
    yield "% @expect sat"
    if levels:
        yield from _optimal_claims(rng, levels)
    if rng.random() < 0.5:
        yield f"% @count {rng.randrange(1, 5)}"
    for tag in (
        *rng.sample(CELL_TAGS, rng.randrange(0, 4)),
        *rng.choices(QUERY_TAGS, k=rng.randrange(0, 3)),
    ):
        yield f"% {tag} {_set(rng)}"


def _case(rng: random.Random, *, optimize: bool, show: str) -> str:
    rules = "\n".join(rng.sample(RULES, rng.randrange(1, 6)))
    objective, levels = rng.choice(OBJECTIVES) if optimize else ("", 0)
    return f"{rules}\n{objective}\n{show}\n" + "\n".join(_claims(rng, levels)) + "\n"


type Table = dict[tuple[str, int], str]


def _legacy(src: str, corpus: Path) -> Table:
    code = "import sys; from elenctic.cli import main; sys.exit(main(sys.argv[1:]))"
    out = subprocess.run(
        [sys.executable, "-c", code, str(corpus), "--format", "json"],
        env={"PYTHONPATH": src, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    document = json.loads(out.stdout[out.stdout.index("{") :])
    return {
        (case["source"], check["line"] if check else 0): check["status"]
        if check
        else case["verdict"]
        for case in document["cases"]
        for check in [None, *case["checks"]]
    } | {(error["source"], 0): "fault" for error in document["errors"]}


def _current(corpus: Path) -> Table:
    found: Table = {}
    for path in sorted(corpus.rglob("*.lp")):
        result = check(Program.read(path))
        if isinstance(result, Report):
            found |= {
                (str(path), f.claim.span.start.line): f.verdict.value for f in result.findings
            }
            found[(str(path), 0)] = result.verdict.value
        elif isinstance(result, Fault):
            found[(str(path), 0)] = "fault"
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_src")
    parser.add_argument("--cases", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--optimize", action="store_true", help="add an objective and optimal claims"
    )
    parser.add_argument(
        "--hide-contraries", action="store_true", help="#show only the positive atoms"
    )
    parser.add_argument("--keep", type=Path, help="write the cases here, and keep them")
    arguments = parser.parse_args()
    rng = random.Random(arguments.seed)
    with tempfile.TemporaryDirectory() as scratch:
        directory = arguments.keep or scratch
        for index in range(arguments.cases):
            case = Path(directory, f"c{index:04d}", f"c{index:04d}.lp")
            case.parent.mkdir(parents=True, exist_ok=True)
            case.write_text(
                _case(
                    rng,
                    optimize=arguments.optimize,
                    show=SHOWN_POSITIVE if arguments.hide_contraries else SHOW,
                )
            )
        old, new = _legacy(arguments.legacy_src, Path(directory)), _current(Path(directory))
    shared = old.keys() & new.keys()
    differing = sorted(k for k in shared if old[k] != new[k])
    print(f"verdicts compared: {len(shared)} ({sum(line == 0 for _, line in shared)} per case)")
    print(f"disagreements: {len(differing)}")
    tally = Counter((old[key], new[key]) for key in differing)
    for (before, after), count in sorted(tally.items()):
        print(f"  {count:3d} legacy={before} current={after}")
    for source, line in differing[:20]:
        print(f"  {source}:{line} legacy={old[source, line]} current={new[source, line]}")
    only = sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys())
    print(f"claims only the current library reports: {len(only[0])}; only legacy: {len(only[1])}")
    return int(bool(differing))


if __name__ == "__main__":
    sys.exit(main())
