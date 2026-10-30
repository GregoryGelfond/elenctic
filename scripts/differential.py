"""Run generated cases through elenctic 0.3 and this library; compare every claim's verdict.

python scripts/differential.py LEGACY_SRC [--cases N] [--seed S]
"""

import argparse
import json
import random
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

from elenctic.check import Report, check
from elenctic.engine import Fault, Program

LITERALS = ("a", "b", "c", "-a", "-b", "-c")
RULES = (
    "{a}.", "{b}.", "{c}.", "a.", "-b.", "a :- not b.", "b :- not a.", "-c :- a.", "c :- b.",
    ":- a, b.", ":- -c, c.", "{a; b; c} = 1.", "1 {b; c} 2.", "-a :- not a, c.", "c :- not -c, b.",
)  # fmt: skip
SHOW = "#show a/0. #show b/0. #show c/0. #show -a/0. #show -b/0. #show -c/0.\n"


def _set(rng: random.Random) -> str:
    return "{ " + ", ".join(rng.sample(LITERALS, rng.choice((1, 1, 2)))) + " }"


def _claims(rng: random.Random) -> Iterator[str]:
    if rng.random() < 0.2:
        yield "% @expect unsat"
        yield from rng.sample(["", "% @count 0"], 1)
        return
    yield "% @expect sat"
    if rng.random() < 0.5:
        yield f"% @count {rng.randrange(1, 5)}"
    for _ in range(rng.randrange(1, 5)):
        tag = rng.choice(
            ("@cautious", "@brave", "@model", "@query yes", "@query no", "@query unknown")
        )
        yield f"% {tag} {_set(rng)}"


def _case(rng: random.Random) -> str:
    rules = "\n".join(rng.sample(RULES, rng.randrange(1, 6)))
    return f"{rules}\n{SHOW}\n" + "\n".join(_claims(rng)) + "\n"


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
    }


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
    parser.add_argument("--keep", type=Path, help="write the cases here, and keep them")
    arguments = parser.parse_args()
    rng = random.Random(arguments.seed)
    with tempfile.TemporaryDirectory() as scratch:
        directory = arguments.keep or scratch
        for index in range(arguments.cases):
            case = Path(directory, f"c{index:04d}", f"c{index:04d}.lp")
            case.parent.mkdir(parents=True, exist_ok=True)
            case.write_text(_case(rng))
        old, new = _legacy(arguments.legacy_src, Path(directory)), _current(Path(directory))
    shared = old.keys() & new.keys()
    differing = sorted(k for k in shared if old[k] != new[k])
    print(f"verdicts compared: {len(shared)} ({sum(line == 0 for _, line in shared)} per case)")
    print(f"disagreements: {len(differing)}")
    for source, line in differing[:20]:
        print(f"  {source}:{line} legacy={old[source, line]} current={new[source, line]}")
    only = sorted(new.keys() - old.keys()), sorted(old.keys() - new.keys())
    print(f"claims only the current library reports: {len(only[0])}; only legacy: {len(only[1])}")
    return int(bool(differing))


if __name__ == "__main__":
    sys.exit(main())
