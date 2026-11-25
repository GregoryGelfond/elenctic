"""The gate is named one way wherever it is named, as `check.sh` runs it."""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
GATE = "pixi run -e theory check"


def test_check_sh_runs_the_gate() -> None:
    assert f"exec {GATE}\n" in (ROOT / "check.sh").read_text(encoding="utf-8")


def test_the_readme_names_the_gate_as_check_sh_runs_it() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    named = re.findall(r"pixi run(?: -e \w+)? check\b", readme)
    assert named
    assert set(named) == {GATE}
