"""Opt-in metered production assembly for the real browser acceptance only."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from learngraph_lite.bootstrap import _create_business_app, build_real_gateway


def create_app():
    if os.environ.get("LEARNGRAPH_REAL_BROWSER_APPROVED") != "1":
        raise RuntimeError("Run the explicit smoke:p0:browser:real entry point.")
    database = Path(os.environ["LEARNGRAPH_DATABASE_PATH"])
    if database.exists():
        raise RuntimeError("Real browser smoke requires a new isolated database.")
    # Reuse the HTTP driver's thread-safe meter without changing production responses.
    spec = importlib.util.spec_from_file_location("real_p0_meter", Path(__file__).with_name("run-real-p0-smoke.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    meter = module.MeteredGateway(build_real_gateway(), limit=14)
    app = _create_business_app(meter, "real", database)

    @app.get("/api/smoke-metrics")
    def metrics():
        return {"model_calls": meter.calls, "model_call_limit": meter.limit, "usage": dict(meter.usage),
                "model": os.environ.get("MODEL_NAME"),
                "provider_host": urlsplit(os.environ.get("MODEL_BASE_URL", "https://api.openai.com/v1")).hostname}

    return app
