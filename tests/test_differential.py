import random
import textwrap
from pathlib import Path

import pytest
from differential import SHOW, SHOWN_POSITIVE, _case, main

from elenctic.check import check
from elenctic.program import Fault, Program
from elenctic.verdicts import Report

# A stand-in for elenctic 0.3: it knows no claims, passes every file and faults the first.
LEGACY = textwrap.dedent(
    """
    import json
    from pathlib import Path

    def main(argv):
        files = sorted(Path(argv[0]).rglob("*.lp"))
        cases = [{"source": str(f), "verdict": "pass", "checks": []} for f in files[1:]]
        print(json.dumps({"cases": cases, "errors": [{"source": str(files[0])}]}))
        return 0
    """
)


def stand_in(src: Path) -> None:
    (src / "elenctic").mkdir(parents=True)
    (src / "elenctic" / "__init__.py").write_text("")
    (src / "elenctic" / "cli.py").write_text(LEGACY)


@pytest.mark.parametrize("optimize", [False, True])
@pytest.mark.parametrize("show", [SHOW, SHOWN_POSITIVE])
def test_every_generated_case_is_a_contract_elenctic_can_read(*, optimize: bool, show: str) -> None:
    rng = random.Random(7)
    cases = [_case(rng, optimize=optimize, show=show) for _ in range(40)]
    assert all(isinstance(check(Program(case)), Report | Fault) for case in cases)
    assert all("% @expect" in case for case in cases)


def test_the_same_seed_makes_the_same_cases() -> None:
    first, second = random.Random(3), random.Random(3)
    assert _case(first, optimize=True, show=SHOW) == _case(second, optimize=True, show=SHOW)


def test_the_comparison_reports_what_the_two_libraries_judge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    stand_in(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["differential", str(tmp_path), "--cases", "6", "--optimize", "--seed", "1"]
    )
    code = main()
    shown = capsys.readouterr().out
    assert "verdicts compared: 6 (6 per case)" in shown
    assert "claims only the current library reports:" in shown
    assert code == int("disagreements: 0" not in shown)


def test_the_cases_can_be_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    legacy, kept = tmp_path / "legacy", tmp_path / "kept"
    stand_in(legacy)
    monkeypatch.setattr(
        "sys.argv", ["differential", str(legacy), "--cases", "3", "--keep", str(kept)]
    )
    main()
    capsys.readouterr()
    assert sorted(p.name for p in kept.rglob("*.lp")) == ["c0000.lp", "c0001.lp", "c0002.lp"]
