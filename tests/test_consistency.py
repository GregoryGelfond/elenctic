"""Mechanical checks that the consistency conventions stay enforced."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from pathlib import Path

import elenctic

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src" / "elenctic"
DOCS = ROOT / "docs"


def _modules() -> Iterator[tuple[str, ast.AST]]:
    for path in sorted(SRC.glob("*.py")):
        yield path.name, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _returns_bool(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    ret = node.returns
    if isinstance(ret, ast.Name) and ret.id == "bool":
        return True
    if isinstance(ret, ast.Subscript) and isinstance(ret.value, ast.Name):
        return ret.value.id in {"TypeIs", "TypeGuard"}
    return False


def test_predicates_open_with_say_whether() -> None:
    outliers: list[str] = []
    for name, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name.startswith("_") or not _returns_bool(node):
                continue
            doc = ast.get_docstring(node)
            if doc is None:
                continue
            first = doc.split("\n", 1)[0]
            if not first.startswith("Say whether"):
                outliers.append(f"{name}:{node.lineno} {node.name}: {first!r}")
    assert outliers == []


def test_every_exported_name_has_a_docstring() -> None:
    missing = [name for name in elenctic.__all__ if inspect.getdoc(getattr(elenctic, name)) is None]
    assert missing == []


def test_stable_model_is_not_user_facing() -> None:
    hits: list[str] = []
    for path in [*SRC.rglob("*.py"), *DOCS.rglob("*.md"), ROOT / "README.md"]:
        if not path.is_file():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "stable model" in line.lower():
                hits.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    assert hits == []


def test_resolve_and_environment_of_have_one_call_site_each() -> None:
    calls: dict[str, list[str]] = {"resolve": [], "Environment.of": []}
    for name, tree in _modules():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            match node.func:
                case ast.Name(id="resolve"):
                    calls["resolve"].append(name)
                case ast.Attribute(value=ast.Name(id="Environment"), attr="of"):
                    calls["Environment.of"].append(name)
    assert calls == {"resolve": ["cli.py"], "Environment.of": ["cli.py"]}


def test_identifiers_are_american() -> None:
    banned = ("Colour", "licence", "analyse", "behaviour", "favourite", "normalise")
    hits: list[str] = []
    for path in SRC.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for attr in ("name", "id", "attr"):
                value = getattr(node, attr, None)
                if isinstance(value, str) and any(b in value for b in banned):
                    hits.append(f"{path.name}:{getattr(node, 'lineno', '?')} {value}")
    assert hits == []


def test_cli_writes_with_write_not_print() -> None:
    tree = ast.parse((SRC / "cli.py").read_text(encoding="utf-8"))
    prints = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]
    assert prints == []
