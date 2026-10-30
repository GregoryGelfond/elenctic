from pathlib import Path

import pytest

from aspnext.check import Report, Verdict, check
from aspnext.engine import Program

CORPUS = sorted(Path(__file__).parent.glob("corpus/*.lp"))


@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.stem)
def test_each_knowledge_representation_case_passes_every_claim(path: Path) -> None:
    report = check(Program.read(path))
    assert isinstance(report, Report)
    assert [f.verdict for f in report.findings] == [Verdict.PASS] * len(report.findings) != []
