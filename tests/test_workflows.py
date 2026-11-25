import re
from pathlib import Path

import pytest

DIRECTORY = Path(__file__).resolve().parent.parent / ".github" / "workflows"
WORKFLOWS = sorted(DIRECTORY.glob("*.yml"))
USES = re.compile(r"^\s*-?\s*uses:\s*(?P<action>\S+)", re.MULTILINE)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_action_a_workflow_uses_is_pinned_to_a_commit(workflow: Path) -> None:
    actions = [found["action"] for found in USES.finditer(workflow.read_text())]
    assert actions
    assert [a for a in actions if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", a)] == []


def test_a_release_is_built_only_once_its_tests_pass_and_published_only_once_built() -> None:
    release = (DIRECTORY / "release.yml").read_text().partition("\njobs:\n")[2]
    jobs = dict(re.findall(r"^  (\w+):\n((?:    .*\n|\n)*)", release, re.MULTILINE))
    assert list(jobs) == ["test", "build", "publish"]
    assert "uv run --locked pytest" in jobs["test"]
    assert re.search(r'python: \["3\.14", "3\.15"\]', jobs["test"])
    assert re.search(r"^    needs: test$", jobs["build"], re.MULTILINE)
    assert re.search(r"^    needs: build$", jobs["publish"], re.MULTILINE)
