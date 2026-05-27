"""
CI guard: verify every module main.py touches actually imports cleanly.

This test exists because of the Task #56 / Task #129 drift class — the Pi was
running with .py files (mqtt_publisher.py, etc.) that had never been committed
to git, so a routine `git pull` + restart left the service unable to import.
Running this test in CI catches that failure mode before it reaches the Pi.

If this test fails, do NOT add stubs or try/except guards. Fix the import:
either commit the missing module, or remove the import from main.py.
"""

from __future__ import annotations

import importlib

# Every module main.py imports directly or transitively. If any of these fails
# to import, main.py will fail on the Pi at restart. Add new entries when
# main.py grows new imports.
MODULES = [
    "src.main",
    "src.config",
    "src.scheduler",
    "src.secrets_loader",
    # Engines
    "src.engine.alert_engine",
    "src.engine.firmware_tracker",
    "src.engine.maintenance_tracker",
    "src.engine.notifier",
    "src.engine.normalizer",
    "src.engine.prediction",
    "src.engine.health_score",
    # Storage
    "src.storage.sqlite_db",
    "src.storage.influx",
    # Collectors
    "src.collectors.base",
    "src.collectors.simulator",
    "src.collectors.snmp_router",
    # Integrations
    "src.integrations.mqtt_publisher",
    "src.integrations.topic_map",
    "src.integrations.latency_tracker",
    # API routers actually wired in main.py
    "src.api.access_requests",
    "src.api.ai",
    "src.api.alerts",
    "src.api.assets",
    "src.api.commands",
    "src.api.correlations",
    "src.api.csv_io",
    "src.api.deploy",
    "src.api.diagnostics",
    "src.api.health",
    "src.api.ingest",
    "src.api.integrations",
    "src.api.notes",
    "src.api.ping_diag",
    "src.api.predictions",
    "src.api.reports",
    "src.api.weather",
    "src.api.ws",
]


def test_all_main_imports_resolve():
    """Every module referenced from main.py must import without raising."""
    failures: list[tuple[str, str]] = []
    for name in MODULES:
        try:
            importlib.import_module(name)
        except Exception as e:
            failures.append((name, f"{type(e).__name__}: {e}"))
    if failures:
        msg = "\n".join(f"  {n}: {err}" for n, err in failures)
        raise AssertionError(
            f"{len(failures)}/{len(MODULES)} module(s) failed to import:\n{msg}\n\n"
            "Fix the underlying module (commit the missing file, install the "
            "missing dependency, or remove the import from main.py)."
        )


def test_main_app_is_fastapi():
    """main.app should be a FastAPI instance with at least the root route."""
    from fastapi import FastAPI

    from src.main import app

    assert isinstance(app, FastAPI), f"src.main.app should be FastAPI, got {type(app)}"
    paths = [r.path for r in app.routes]
    assert "/" in paths, "Root route '/' should be registered"
    # At least one /api/v1 route should be present (sanity check on prefix)
    api_v1_count = sum(1 for p in paths if p.startswith("/api/v1"))
    assert api_v1_count > 5, f"Expected several /api/v1 routes, found {api_v1_count}"


def test_main_lab_assets_registry():
    """Asset registry should cover the 7 documented lab assets."""
    from src.main import LAB_ASSETS

    asset_ids = {a["id"] for a in LAB_ASSETS}
    expected = {"RTR-01", "SW-01", "EDGE-01", "RAD-01", "RAD-02", "RTU-01", "EFM-01"}
    assert expected.issubset(asset_ids), f"Missing assets: {expected - asset_ids}"
