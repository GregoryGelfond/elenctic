"""Write the JSON Schema of a `--json` document from the result types."""

from pathlib import Path

from elenctic.json_view import schema_text

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs" / "reference" / "output-v1.schema.json"


def render() -> str:
    """Render the schema file: derived from the types, never hand-maintained."""
    return schema_text()


if __name__ == "__main__":
    TARGET.write_text(render())
