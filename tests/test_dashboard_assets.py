"""Static check: every dashboard asset referenced by Aevus_Console.html
must exist in the repo AND be in the deploy.sh whitelist.

Why this exists
---------------
On 2026-05-30 the weather/map/network/solar pages all rendered blank because
`dashboard/leaflet.min.js` and `dashboard/leaflet.min.css` returned 404 in
production. They existed in the repo, but `deploy.sh`'s `DASHBOARD_FILES`
whitelist didn't include them — so the deploy never copied them to EC2.
Without Leaflet, `L is not defined` → the map IIFE threw → the cascade of
sequential render IIFEs all aborted → multiple pages went dark.

This test catches that whole class of bug at PR time:

  1. Walk `dashboard/Aevus_Console.html` for every `<script src=...>` and
     `<link href=...>` that references a local dashboard asset.
  2. Assert each referenced file exists in `dashboard/` in the repo.
  3. Assert each referenced file is listed in `deploy.sh`'s DASHBOARD_FILES
     (or under a DASHBOARD_DIRS prefix), so the deploy actually ships it.

If a new `<script>` lands in the HTML pointing at a file that isn't in the
repo or isn't in the deploy whitelist, this test fails — no more silent
"works locally, 404 in prod" outages.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTML = REPO / "dashboard" / "Aevus_Console.html"
DEPLOY_SH = REPO / "deploy.sh"

# Hosts that aren't us — don't validate (CDN, fonts.googleapis.com, etc).
EXTERNAL_PREFIXES = ("http://", "https://", "//", "data:")


def _referenced_local_assets() -> set[str]:
    """All dashboard-local asset paths the HTML loads at runtime.

    Returns set of paths relative to `dashboard/` (e.g. "leaflet.min.js",
    "icons/icon-192.png").
    """
    src = HTML.read_text()
    refs = re.findall(r'<(?:script|link)[^>]*?\s(?:src|href)=["\']([^"\']+)["\']', src)
    local: set[str] = set()
    for ref in refs:
        if any(ref.startswith(p) for p in EXTERNAL_PREFIXES):
            continue
        # Strip cache-buster + fragment.
        path = ref.split("?")[0].split("#")[0]
        if path.startswith("/dashboard/"):
            local.add(path[len("/dashboard/"):])
        elif "/" in path and not path.startswith("/") or "." in path and not path.startswith("/"):
            local.add(path)
    return local


def _deploy_whitelist() -> tuple[set[str], set[str]]:
    """Parse DASHBOARD_FILES and DASHBOARD_DIRS from deploy.sh.

    Returns (set of file paths, set of dir prefixes), each relative to `dashboard/`.
    """
    src = DEPLOY_SH.read_text()

    def _extract(var: str) -> set[str]:
        # Match VAR="..." possibly multi-line with backslash continuations.
        m = re.search(rf'{var}="((?:[^"\\]|\\.)*?)"', src, re.DOTALL)
        if not m:
            return set()
        # Collapse line-continuations + whitespace.
        body = re.sub(r"\\\s*\n", " ", m.group(1))
        items: set[str] = set()
        for token in body.split():
            if token.startswith("dashboard/"):
                items.add(token[len("dashboard/"):])
        return items

    return _extract("DASHBOARD_FILES"), _extract("DASHBOARD_DIRS")


def _covered_by_dirs(asset: str, dirs: set[str]) -> bool:
    """True if `asset` lives under one of the whitelisted directory prefixes."""
    return any(asset == d or asset.startswith(d + "/") for d in dirs)


def test_every_referenced_asset_exists_in_repo():
    """Every <script>/<link> the HTML loads must be a real file in dashboard/.

    Caught: an HTML reference to a file someone forgot to commit, or a typo
    in the path. Both would 404 in production.
    """
    missing = sorted(
        asset for asset in _referenced_local_assets()
        if not (REPO / "dashboard" / asset).is_file()
    )
    assert not missing, (
        "Aevus_Console.html references dashboard assets that don't exist in the repo:\n"
        + "\n".join(f"  - dashboard/{a}" for a in missing)
        + "\n\nFix: commit the missing file, or correct the path in the HTML."
    )


def test_every_referenced_asset_is_in_deploy_whitelist():
    """Every dashboard asset the HTML loads must be in deploy.sh's whitelist.

    Caught: this is the exact 2026-05-30 outage — Leaflet was in the repo
    but not in DASHBOARD_FILES, so the deploy didn't ship it and production
    404'd. The blank map/forecast/etc. cascade followed from there.
    """
    files, dirs = _deploy_whitelist()
    missing = sorted(
        asset for asset in _referenced_local_assets()
        if asset not in files and not _covered_by_dirs(asset, dirs)
    )
    assert not missing, (
        "Aevus_Console.html references dashboard assets that deploy.sh won't ship:\n"
        + "\n".join(f"  - dashboard/{a}" for a in missing)
        + "\n\nFix: add each to DASHBOARD_FILES (or DASHBOARD_DIRS) in deploy.sh."
    )
