"""Guard: the OpenAPI schema must build, so /openapi.json + /docs work.

Regression for #210: a model whose field type (e.g. `datetime`) — or a router
whose request/response type — is imported ONLY under `if TYPE_CHECKING:` while
the module uses `from __future__ import annotations` cannot be resolved by
Pydantic at schema-build time. FastAPI then raises while generating the schema,
so `/openapi.json` returns 500 and `/docs` renders blank.

This test builds the whole schema and asserts the previously-broken models are
present + resolvable. It fails loudly if any router/model regresses the same way
(import a schema type under TYPE_CHECKING-only) — catching the entire class.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.main import app


def test_openapi_schema_builds():
    schema = app.openapi()
    assert schema["openapi"].startswith("3."), "missing/invalid openapi version"
    assert schema["paths"], "no paths in the OpenAPI schema"
    schemas = schema["components"]["schemas"]
    # the models that previously broke the build must be present + resolvable
    for model in ("ShelveResponse", "CommandRequest"):
        assert model in schemas, f"{model} missing from OpenAPI schema (TYPE_CHECKING-only import?)"


def test_openapi_json_endpoint_not_500():
    with TestClient(app) as c:
        r = c.get("/openapi.json")
        assert r.status_code == 200, f"/openapi.json returned {r.status_code} (schema build failed?)"
        assert r.json()["info"]["title"]
