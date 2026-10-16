from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_demo_runner():
    spec = importlib.util.spec_from_file_location("fixture_demo_runner", ROOT / "scripts" / "run-fixture-demo.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load fixture demo runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_fixture_demo_runs_full_offline_journey():
    runner = load_demo_runner()
    data = runner.build_demo()

    assert data["mode"] == "fixture"
    assert data["graph_nodes"] == "8"
    assert data["citation_count"] != "0"
    assert data["empty_citation_count"] == "0"
    assert data["mastery"] == "proficient"
    assert data["proposal_status"] == "accepted"


def test_fixture_demo_document_marks_evidence_boundary():
    runner = load_demo_runner()
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "fixture-demo.md"
        runner.write_demo(output)
        text = output.read_text(encoding="utf-8")

    assert "deterministic fixture demo" in text
    assert "does not call a real model" in text
    assert "Real model smoke" in text
    assert "not exercised by this in-memory demo" in text
    assert "[current acceptance status](../QUALITY_SCORE.md)" in text
    assert "still separate M5 work" not in text
