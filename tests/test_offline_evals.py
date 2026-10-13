from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_eval_runner():
    spec = importlib.util.spec_from_file_location("offline_eval_runner", ROOT / "evals" / "run.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load eval runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_offline_m5_eval_suite_has_20_passing_cases():
    runner = load_eval_runner()
    suite = runner.load_cases()
    results = runner.run_suite()

    assert len(suite["cases"]) == 20
    assert len(results) == 20
    assert all(result.status == "passed" for result in results)


def test_offline_m5_eval_report_marks_fixture_not_real_model():
    runner = load_eval_runner()
    with tempfile.TemporaryDirectory() as tmpdir:
        report_path = Path(tmpdir) / "report.md"
        results = runner.write_report(report_path)
        report = report_path.read_text(encoding="utf-8")

    assert len(results) == 20
    assert "20/20 cases passed" in report
    assert "Real model smoke: not run" in report
    assert "must not be used as evidence of real model quality" in report
