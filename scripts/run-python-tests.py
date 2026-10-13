#!/usr/bin/env python
from __future__ import annotations

import importlib.util
import inspect
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
sys.path.insert(0, str(SRC))


def load_module(path: Path):
    name = "local_" + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    failures: list[str] = []
    count = 0
    for path in sorted(TESTS.glob("test_*.py")):
        module = load_module(path)
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith("test_"):
                continue
            count += 1
            try:
                func()
            except Exception:
                failures.append(f"{path.name}::{name}\n{traceback.format_exc()}")
    if failures:
        print("\n".join(failures))
        print(f"{len(failures)} failed, {count} collected")
        return 1
    print(f"{count} Python tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
