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
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HTML = REPO / "dashboard" / "Aevus_Console.html"

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
            local.add(path[len("/dashboard/") :])
        elif "/" in path and not path.startswith("/") or "." in path and not path.startswith("/"):
            local.add(path)
    return local


def _raw_local_refs() -> list[str]:
    """Raw (un-normalized) script/link refs to local dashboard assets, as written."""
    src = HTML.read_text()
    refs = re.findall(r'<(?:script|link)[^>]*?\s(?:src|href)=["\']([^"\']+)["\']', src)
    return [ref for ref in refs if not any(ref.startswith(p) for p in EXTERNAL_PREFIXES)]


def _git_tracked_dashboard() -> set[str]:
    """Dashboard assets tracked by git, relative to `dashboard/`.

    The production deploy (deploy/deploy.sh) does `git reset --hard origin/main`,
    so EVERY committed file ships — there is no per-file whitelist anymore. The
    invariant that protects against the 2026-05-30 Leaflet 404 is therefore simply
    "the referenced asset is committed." (This is strictly safer than the old
    whitelist, whose missing entry caused that very outage.)
    """
    out = subprocess.run(
        ["git", "ls-files", "dashboard/"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    tracked: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("dashboard/"):
            tracked.add(line[len("dashboard/") :])
    return tracked


def test_every_referenced_asset_exists_in_repo():
    """Every <script>/<link> the HTML loads must be a real file in dashboard/.

    Caught: an HTML reference to a file someone forgot to commit, or a typo
    in the path. Both would 404 in production.
    """
    missing = sorted(asset for asset in _referenced_local_assets() if not (REPO / "dashboard" / asset).is_file())
    assert not missing, (
        "Aevus_Console.html references dashboard assets that don't exist in the repo:\n"
        + "\n".join(f"  - dashboard/{a}" for a in missing)
        + "\n\nFix: commit the missing file, or correct the path in the HTML."
    )


def test_local_assets_use_absolute_dashboard_path():
    """Local dashboard assets must be loaded via absolute '/dashboard/...' paths.

    Caught: the 2026-06-03 blank-map outage. Aevus_Console.html is served at root
    ('/'), but MapLibre + Leaflet were loaded via RELATIVE paths
    (e.g. `src="maplibre-gl.min.js"`), which the browser resolves to
    `/maplibre-gl.min.js` -> 404. `maplibregl` was then undefined, the map never
    built, and the whole Map page (and the Killdeer 3D twin on top of it) went blank.

    The earlier whitelist tests didn't catch it because they normalize '/dashboard/X'
    and bare 'X' to the same asset and only check existence + whitelist — never that
    the path is absolute. This test closes that gap.
    """
    bad = [r for r in _raw_local_refs() if not r.split("?")[0].split("#")[0].startswith("/dashboard/")]
    assert not bad, (
        "Aevus_Console.html loads dashboard assets via non-absolute paths "
        "(these 404 because the page is served at '/'):\n"
        + "\n".join(f"  - {b}" for b in bad)
        + "\n\nFix: use absolute '/dashboard/<file>' paths for every local script/link."
    )


def test_every_referenced_asset_is_git_tracked():
    """Every dashboard asset the HTML loads must be committed to git.

    The deploy does `git reset --hard origin/main`, so a committed file always
    ships — and an UNcommitted one never does. This is the modern form of the
    2026-05-30 Leaflet-404 guard: instead of "is it in the deploy whitelist?"
    (whitelist removed — it was the footgun), assert "is it committed?".
    """
    tracked = _git_tracked_dashboard()
    missing = sorted(asset for asset in _referenced_local_assets() if asset not in tracked)
    assert not missing, (
        "Aevus_Console.html references dashboard assets that aren't committed to git "
        "(so `git reset --hard origin/main` won't ship them):\n"
        + "\n".join(f"  - dashboard/{a}" for a in missing)
        + "\n\nFix: git add + commit each referenced asset."
    )
