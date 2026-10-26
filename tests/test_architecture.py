"""Enforce the Architecture rules in CLAUDE.md by parsing imports (no code is executed)."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "backend" / "app"

# layer -> app layers it may import (its own layer is always allowed)
ALLOWED = {
    "main": {"controllers", "clients", "core"},  # composition root
    "controllers": {"schemas", "services", "graph", "models", "core"},  # models: enums as path params
    "graph": {"services", "models", "core"},
    "services": {"clients", "models", "core"},
    "clients": {"models", "core"},
    "schemas": {"models"},
    "models": {"core"},
    "core": set(),
}
# The single documented exception: RT-104 enforced on the domain model.
EXCEPTIONS = {("models/domain.py", "backend.app.services.freshness")}


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _files():
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP)
        layer = "main" if rel.parts == ("main.py",) else rel.parts[0]
        if layer.endswith(".py"):
            continue  # backend/app/__init__.py
        yield path, rel.as_posix(), layer


def test_backend_never_imports_mcp_server():
    offenders = [
        f"backend/app/{rel} -> {mod}"
        for path, rel, _ in _files()
        for mod in _imports(path)
        if mod == "mcp_server" or mod.startswith("mcp_server.")
    ]
    assert offenders == []


def test_fastapi_only_in_controllers_and_main():
    offenders = [
        f"backend/app/{rel} -> {mod}"
        for path, rel, layer in _files()
        if layer not in {"controllers", "main"}
        for mod in _imports(path)
        if mod.split(".")[0] in {"fastapi", "starlette"}
    ]
    assert offenders == []


def test_imports_are_one_way():
    offenders = []
    for path, rel, layer in _files():
        for mod in _imports(path):
            if not mod.startswith("backend.app."):
                continue
            target = mod.split(".")[2]
            if target == layer or target in ALLOWED[layer] or (rel, mod) in EXCEPTIONS:
                continue
            offenders.append(f"backend/app/{rel} ({layer}) -> {mod}")
    assert offenders == []


def test_every_layer_is_known():
    assert {layer for _, _, layer in _files()} <= ALLOWED.keys()
