"""Write the JSON Schema of a `--json` document from the result types."""

import json
from pathlib import Path

from elenctic.json_view import schema_document

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs" / "reference" / "output-v1.schema.json"


def render() -> str:
    """Render the schema file: derived from the types, never hand-maintained."""
    return json.dumps(schema_document(), indent=2) + "\n"


if __name__ == "__main__":
    TARGET.write_text(render())
