"""Offline tests of the opt-in real P0 driver; no developer config/provider calls."""
import importlib.util
import tempfile
from pathlib import Path

from learngraph_lite.agent_core import ModelResponse
from learngraph_lite.bootstrap import _create_business_app
from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel


def driver():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run-real-p0-smoke.py"
    spec = importlib.util.spec_from_file_location("real_p0_driver", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_p0_driver_checks_http_tool_artifacts_and_reopen_with_fixture_only():
    module = driver()
    meters = []
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "smoke.sqlite3"
        def factory(restore=False):
            meter = module.MeteredGateway(BusinessFixtureModel(), limit=0 if restore else 12)
            meters.append(meter)
            return _create_business_app(meter, "fixture", database)

        report = {"mode": "fixture"}
        module.journey(factory, report)
        assert [item["phase"] for item in report["runs"]] == ["clarify", "graph", "teaching", "button-exercise"]
        assert all(item["status"] == "completed" for item in report["runs"])
        assert "sqlite-reopen-without-model-calls" in report["checks"]
        assert meters[0].calls == 7 and meters[1].calls == 0


def test_real_p0_meter_limits_complete_and_stream_calls_before_dispatch():
    module = driver()
    class Model:
        def complete(self, messages, tools):
            return ModelResponse("done", usage={"total_tokens": 3})
        def stream_complete(self, messages, tools, on_delta):
            on_delta("done")
            return ModelResponse("done", usage={"total_tokens": 5})

    meter = module.MeteredGateway(Model(), limit=2)
    meter.complete((), ())
    meter.stream_complete((), (), lambda text: None)
    assert meter.calls == 2 and meter.usage == {"total_tokens": 8}
    try:
        meter.complete((), ())
    except module.SmokeFailure:
        pass
    else:
        raise AssertionError("driver exceeded its provider call limit")
    assert meter.calls == 2
