import re
from pathlib import Path

import pytest

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))
USES = re.compile(r"^\s*-?\s*uses:\s*(?P<action>\S+)", re.MULTILINE)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_every_action_a_workflow_uses_is_pinned_to_a_commit(workflow: Path) -> None:
    actions = [found["action"] for found in USES.finditer(workflow.read_text())]
    assert actions
    assert [a for a in actions if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", a)] == []
