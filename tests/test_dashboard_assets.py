"""Static + routing checks for the PARKED old broad console.

The old console (dashboard/Aevus_Console.html, award-map, the dashboard-staging
mirror) was retired in favor of Aevus Comms at /comms/. The code is preserved in
git (tag `retired/old-dashboard`); it must not be served, and nothing the public
front door touches may still point at it.

What this guards:

  1. The retired pages are gone from the tree (recover them from the git tag).
  2. `/` redirects to the Comms console (query kept, so ?demo=true survives)
     instead of rendering a page.
  3. The static mounts serve EVERY file on disk, including untracked on-box
     leftovers (Aevus_Console.html.bak-*), so a request-time guard 404s any
     retired page name or .bak copy under /dashboard and /staging.
  4. login.html lands on /comms after sign-in, has no anonymous "Explore Demo"
     door, and never redirects to the retired console.
  5. sw.js is a tombstone (no precache, no fetch handler) and the manifests start
     at /comms/, so a returning browser cannot resurrect the cached old console.
  6. The requester "Explore Demo" email link is the synthetic Comms console.

History: this file used to assert every asset referenced by Aevus_Console.html
existed and was committed (the 2026-05-30 Leaflet 404 / 2026-06-03 blank-map
outages). That console is no longer served, so those guards retired with it. The
equivalent protection for the login page is test_login_local_assets_are_committed.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import access_requests
from src.main import app

REPO = Path(__file__).resolve().parent.parent
DASH = REPO / "dashboard"
STAGING = REPO / "dashboard-staging"

RETIRED_PAGES = (
    "Aevus_Console.html",
    "award-map.html",
    "topology.html",
    "twin-showcase.html",
    "loader-preview.html",
    "loader-record.html",
)
COMMS_DOOR = "/comms/Aevus_Comms_Console.html"

# Local assets login.html loads that are deployed to the box out of band (NOT in git).
# Tracked-ness is intentionally not asserted for these; they must exist on the box.
BOX_ONLY_LOGIN_ASSETS = {"amazon-cognito-identity.min.js"}


@pytest.fixture(scope="module")
def client():
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = ""
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app, follow_redirects=False) as c:
            yield c


def _tracked(prefix: str) -> set[str]:
    out = subprocess.run(["git", "ls-files", prefix], cwd=REPO, capture_output=True, text=True, check=True).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


# 1. retired pages are gone from the tree -------------------------------------


def test_retired_pages_removed_from_tree():
    present = [f"{d.name}/{p}" for d in (DASH, STAGING) for p in RETIRED_PAGES if (d / p).exists()]
    assert not present, (
        "Retired old-console pages are back in the tree: "
        + ", ".join(present)
        + ". They live in git tag retired/old-dashboard; do not re-add them."
    )


def test_no_live_route_serves_the_old_console():
    """No source file wires the old console back in (the only mention allowed is the guard)."""
    src = (REPO / "src" / "main.py").read_text()
    assert "_INDEX_HTML" not in src
    assert 'DASHBOARD_DIR / "Aevus_Console.html"' not in src
    for py in (REPO / "src").rglob("*.py"):
        text = py.read_text()
        for m in re.finditer(r"/dashboard/Aevus_Console\.html", text):
            pytest.fail(f"{py.relative_to(REPO)} links to the retired console near offset {m.start()}")


# 2. root redirect -------------------------------------------------------------


def test_root_redirects_to_comms(client):
    r = client.get("/")
    assert r.status_code == 302
    assert r.headers["location"] == COMMS_DOOR


def test_root_redirect_keeps_demo_query(client):
    r = client.get("/?demo=true")
    assert r.status_code == 302
    assert r.headers["location"] == COMMS_DOOR + "?demo=true"


def test_root_needs_no_api_key():
    with patch("src.api.auth.settings") as mock_settings:
        mock_settings.api_key = "test-secret-key"
        mock_settings.api_key_header = "X-API-Key"
        with TestClient(app, follow_redirects=False) as c:
            assert c.get("/").status_code == 302


# 3. request-time guard --------------------------------------------------------


@pytest.mark.parametrize("base", ["/dashboard", "/staging"])
@pytest.mark.parametrize("name", RETIRED_PAGES)
def test_retired_pages_404(client, base, name):
    assert client.get(f"{base}/{name}").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard/Aevus_Console.html.bak-20260525-163748",  # untracked on-box leftover
        "/dashboard/aevus_console.html",  # case variation
        "/dashboard//Aevus_Console.html",  # double slash
        "/dashboard/./Aevus_Console.html",
        "/dashboard/x/../Aevus_Console.html",
        "/dashboard/login.html.bak-retire-20261012-070504",  # any .bak copy
        "/dashboard/comms/Aevus_Comms_Console.html.bak-tier1-20261014-142028",
        "/staging/Aevus_Console.html.bak-anything",
    ],
)
def test_guard_blocks_leftovers_and_path_tricks(client, path):
    assert client.get(path).status_code == 404


def test_guard_leaves_real_assets_alone(client):
    assert client.get("/dashboard/login.html").status_code == 200
    assert client.get("/dashboard/favicon.svg").status_code == 200
    assert client.get("/login").status_code == 200


# 4. login ---------------------------------------------------------------------


@pytest.mark.parametrize("login", [DASH / "login.html", STAGING / "login.html"])
def test_login_lands_on_comms_and_has_no_anonymous_door(login):
    html = login.read_text()
    assert "Aevus_Console" not in re.sub(r"/Aevus_Console\|", "", html), "login still points at the retired console"
    assert "enterDemo" not in html and "Explore Demo" not in html, "anonymous demo door is back on the login page"
    assert COMMS_DOOR in html
    # Every post-sign-in redirect goes through the env-aware comms target.
    redirects = re.findall(r"window\.location\.href\s*=\s*([^;]+);", html)
    assert redirects, "no post-sign-in redirect found in login.html"
    for target in redirects:
        assert "comms" in target.lower() or "consoleUrl()" in target, f"redirect not pointed at comms: {target}"


def test_login_ignores_a_stale_return_to_the_old_console():
    """A bookmarked ?return=...Aevus_Console must not send a signed-in user back to the parked page."""
    html = (DASH / "login.html").read_text()
    assert re.search(r"returnUrl\s*&&\s*/Aevus_Console", html)


def test_login_local_assets_are_committed():
    html = (DASH / "login.html").read_text()
    refs = re.findall(r'<(?:script|link)[^>]*?\s(?:src|href)=["\']([^"\']+)["\']', html)
    tracked = _tracked("dashboard/")
    missing = []
    for ref in refs:
        if ref.startswith(("http://", "https://", "//", "data:")):
            continue
        path = ref.split("?")[0].split("#")[0]
        assert path.startswith("/dashboard/"), f"login asset must use an absolute /dashboard/ path: {ref}"
        rel = path[len("/dashboard/") :]
        if rel in BOX_ONLY_LOGIN_ASSETS:
            continue
        if f"dashboard/{rel}" not in tracked or not (DASH / rel).is_file():
            missing.append(rel)
    assert not missing, f"login.html loads assets that are not committed: {missing}"


# 5. service worker + manifest -------------------------------------------------


@pytest.mark.parametrize("sw", [DASH / "sw.js", STAGING / "sw.js"])
def test_service_worker_is_a_tombstone(sw):
    js = sw.read_text()
    assert "unregister" in js and "caches.delete" in js
    assert "addEventListener('fetch'" not in js and 'addEventListener("fetch"' not in js
    assert "cache.addAll" not in js and "SHELL_ASSETS" not in js
    assert "Aevus_Console" not in js and "CACHE_NAME" not in js


@pytest.mark.parametrize("manifest", [DASH / "manifest.json", STAGING / "manifest.json"])
def test_manifest_starts_at_comms(manifest):
    data = json.loads(manifest.read_text())
    assert data["start_url"] == COMMS_DOOR
    assert "Aevus_Console" not in manifest.read_text()
    for shortcut in data.get("shortcuts", []):
        assert shortcut["url"].startswith("/comms/")


# 6. emails --------------------------------------------------------------------


def test_demo_email_link_is_the_synthetic_comms_console():
    assert access_requests.DEMO_CONSOLE_URL == "https://aevus.intrepidlogic.io" + COMMS_DOOR + "?demo=true"
    assert "Aevus_Console" not in (REPO / "src" / "api" / "access_requests.py").read_text()
