"""Brand lock-in guard: there is exactly ONE Aevus logo, and it is canonical.

Why this exists
---------------
On 2026-06-04 a logo audit found the Aevus mark had silently drifted into
**4 different "A" geometries across 3 color schemes**:

  1. canonical smooth "A"  (path `M487.44…`) — teal #06B6D4 + indigo crossbar
  2. a blue->purple GRADIENT block-"A" (stops #6D5BD0 / #9B70F6, path `M48 0 L2 95…`)
     — used in the live dashboard loader + topbar (what users actually saw)
  3. a simplified "A"  (`M16 4L6 28…` / `M14 2L3 26…`) — favicon, login, reports
  4. wrong-glyph raster PWA icons (one rendered as an "H")

The old navy crossbar (#0B1020) was also invisible against the dark platform
background (#0B1020), so the mark looked broken. We collapsed everything to a
single canonical vector — teal #06B6D4 "A" + indigo #6366F1 crossbar — sourced
from `dashboard/brand/aevus-icon.svg` (mark) and `dashboard/brand/aevus-logo.svg`
(full lockup). See `docs/BRAND_LOGO_LOCKIN.md`.

This test fails the build if any drift variant reappears in a SERVED surface
(dashboard pages/JS + server-side report/email generators). Snapshot/mirror
trees (`dashboard-staging/`, `award-recovery/`) are intentionally out of scope —
they are not served and are frozen evidence copies.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Canonical artefacts that MUST exist (single source of truth).
CANONICAL_ASSETS = [
    "dashboard/brand/aevus-logo.svg",  # full lockup (icon + wordmark)
    "dashboard/brand/aevus-icon.svg",  # mark only
    "dashboard/favicon.svg",
    "dashboard/icons/icon-192.png",
    "dashboard/icons/icon-512.png",
]

# Canonical geometry signatures.
CANONICAL_A = "M487.44"  # the teal "A"
CANONICAL_CROSSBAR = "M511.32"  # the crossbar (must be indigo, not navy/teal)
TEAL = "#06b6d4"  # primary (case-insensitive match)
INDIGO = "#6366f1"  # secondary accent (case-insensitive match)

# Drift signatures that must NEVER appear in a served surface.
# Each maps a signature -> human explanation for the failure message.
#
# NOTE: we key on logo *path geometry*, NOT color. The old gradient logo used
# purple #6D5BD0/#9B70F6, but those same hexes are legitimately used elsewhere in
# the UI (RAD-02 device color, RF page accents, loader animation, sparklines), so
# matching on color would produce false positives. Each retired logo has a unique
# path-`d` signature, which identifies it unambiguously.
FORBIDDEN = {
    "M48 0 L2 95": "block-'A' gradient geometry (old loader/topbar logo)",
    "M16 4L6 28": "simplified 'A' geometry (old favicon/reports logo)",
    "M14 2L3 26": "simplified 'A' geometry (old login logo)",
}

# Served / source surfaces to scan. Explicit list (not a glob) so vendored
# libraries (three.min.js, leaflet/maplibre) and snapshot trees stay excluded.
SERVED_GLOBS = [
    "dashboard/*.html",
    "dashboard/brand/*.svg",
    "dashboard/favicon.svg",
]
# JS we author (exclude vendored *.min.js libs by name).
VENDORED = {"three.min.js", "leaflet.min.js", "maplibre-gl.min.js"}
SOURCE_GLOBS = [
    "src/api/reports.py",
    "src/api/access_requests.py",
]


def _served_files() -> list[Path]:
    files: list[Path] = []
    for g in SERVED_GLOBS:
        files.extend(REPO.glob(g))
    # Authored dashboard JS (award-client.js, api-client.js, etc.), excluding vendored libs.
    for p in REPO.glob("dashboard/*.js"):
        if p.name not in VENDORED:
            files.append(p)
    for g in SOURCE_GLOBS:
        p = REPO / g
        if p.is_file():
            files.append(p)
    # Dedupe, stable order.
    return sorted(set(files))


def test_canonical_assets_exist():
    """The single-source-of-truth files must be present."""
    missing = [a for a in CANONICAL_ASSETS if not (REPO / a).is_file()]
    assert not missing, (
        "Canonical Aevus brand assets are missing:\n"
        + "\n".join(f"  - {a}" for a in missing)
        + "\n\nThese are the one source of truth. Restore them; do not inline new logo copies."
    )


def test_no_drift_logo_variants_in_served_surfaces():
    """No served page/JS/report may contain a non-canonical logo variant."""
    hits: list[str] = []
    for path in _served_files():
        text = path.read_text(errors="ignore")
        for sig, why in FORBIDDEN.items():
            if sig in text:
                rel = path.relative_to(REPO)
                hits.append(f"  - {rel}: contains '{sig}'  ({why})")
    assert not hits, (
        "Non-canonical Aevus logo variant(s) found in served surfaces:\n"
        + "\n".join(sorted(hits))
        + "\n\nFix: replace with the canonical mark from dashboard/brand/aevus-icon.svg "
        "(teal #06B6D4 'A' + indigo #6366F1 crossbar). See docs/BRAND_LOGO_LOCKIN.md."
    )


def test_favicon_uses_canonical_geometry():
    """favicon.svg must use the canonical 'A', not the old simplified glyph."""
    fav = (REPO / "dashboard" / "favicon.svg").read_text()
    assert CANONICAL_A in fav, (
        "dashboard/favicon.svg is not the canonical mark (missing the 'M487.44' path). "
        "Regenerate it from dashboard/brand/aevus-icon.svg."
    )


def test_canonical_icon_crossbar_is_indigo():
    """The canonical mark's crossbar must be indigo (the whole point of the recolor)."""
    icon = (REPO / "dashboard" / "brand" / "aevus-icon.svg").read_text().lower()
    assert CANONICAL_CROSSBAR.lower() in icon and INDIGO in icon, (
        "dashboard/brand/aevus-icon.svg must contain the crossbar path (M511.32) "
        f"filled with indigo {INDIGO}. The old navy #0B1020 crossbar was invisible "
        "on the dark platform — that's why we recolored it."
    )
    assert TEAL in icon, "Canonical icon lost its teal 'A' (#06B6D4)."


def test_brand_assets_are_git_tracked():
    """The canonical brand/ assets must be committed (else prod 404s).

    The deploy does `git reset --hard origin/main`, so anything committed ships.
    (The old DASHBOARD_FILES whitelist was removed — it was the footgun behind the
    2026-05-30 Leaflet outage; "is it committed?" is the correct, safer invariant.)
    """
    import subprocess

    tracked = set(
        subprocess.run(
            ["git", "ls-files", "dashboard/brand/"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )
    for asset in ("dashboard/brand/aevus-logo.svg", "dashboard/brand/aevus-icon.svg"):
        assert asset in tracked, (
            f"{asset} is not committed to git, so `git reset --hard origin/main` won't ship it. git add + commit it."
        )
