#!/usr/bin/env python
"""Check lightweight Python import boundaries for LearnGraph Lite."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "learngraph_lite"

RULES = {
    "agent_core": (
        "learngraph_lite.application",
        "learngraph_lite.domain",
        "learngraph_lite.infrastructure",
        "learngraph_lite.presentation",
    ),
    "domain": (
        "learngraph_lite.agent_core",
        "learngraph_lite.application",
        "learngraph_lite.infrastructure",
        "learngraph_lite.presentation",
    ),
    "application": (
        "learngraph_lite.infrastructure",
        "learngraph_lite.presentation",
    ),
}


def imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def layer_for(path: Path) -> str | None:
    relative = path.relative_to(SRC)
    return relative.parts[0] if relative.parts else None


def main() -> int:
    errors: list[str] = []
    for file in SRC.rglob("*.py"):
        layer = layer_for(file)
        forbidden = RULES.get(layer)
        if not forbidden:
            continue
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for module in imported_modules(tree):
            if module.startswith(forbidden):
                errors.append(f"{file.relative_to(ROOT)} imports forbidden module {module}")
    if errors:
        print("\n".join(errors))
        return 1
    print("Python import boundaries passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
