"""Offline checks for the metered real browser server; never a real acceptance."""

from pathlib import Path
import importlib.util
import os
import tempfile
from unittest.mock import patch

from fastapi.testclient import TestClient

from learngraph_lite.infrastructure.business_fixture import BusinessFixtureModel


def browser_server():
    path = Path(__file__).resolve().parents[1] / "scripts" / "real_browser_app.py"
    spec = importlib.util.spec_from_file_location("real_browser_server", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_browser_factory_is_opt_in_and_refuses_existing_database_before_model():
    module = browser_server()
    with tempfile.TemporaryDirectory() as directory, patch.object(module, "build_real_gateway") as build:
        database = Path(directory) / "evidence.sqlite3"
        database.write_bytes(b"existing evidence")
        for env in ({}, {"LEARNGRAPH_REAL_BROWSER_APPROVED": "1", "LEARNGRAPH_DATABASE_PATH": str(database)}):
            with patch.dict(os.environ, env, clear=True):
                try:
                    module.create_app()
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("real browser factory bypassed opt-in/new-database checks")
        assert database.read_bytes() == b"existing evidence"
        build.assert_not_called()


def test_browser_metrics_are_public_metadata_only_and_reads_never_dispatch_model():
    module = browser_server()
    with tempfile.TemporaryDirectory() as directory, patch.object(module, "build_real_gateway", return_value=BusinessFixtureModel()):
        env = {"LEARNGRAPH_REAL_BROWSER_APPROVED": "1", "LEARNGRAPH_DATABASE_PATH": str(Path(directory) / "new.sqlite3"),
               "MODEL_NAME": "offline-stub", "MODEL_BASE_URL": "https://private-key:password@provider.example/v1",
               "MODEL_API_KEY": "never-report-this-key"}
        with patch.dict(os.environ, env, clear=True), TestClient(module.create_app(), base_url="http://localhost") as api:
            metrics = api.get("/api/smoke-metrics").json()
            assert metrics == {"model_calls": 0, "model_call_limit": 14, "usage": {},
                               "model": "offline-stub", "provider_host": "provider.example"}
            assert "private-key" not in str(metrics) and "password" not in str(metrics) and "never-report" not in str(metrics)
            assert api.get("/api/model/status").json() == {"mode": "real", "configured": True}
            assert api.get("/api/goals").json() == []
            assert api.get("/api/smoke-metrics").json()["model_calls"] == 0
