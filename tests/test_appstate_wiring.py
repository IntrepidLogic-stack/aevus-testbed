"""Static check: every `app_state.X` referenced in src/api/*.py exists on AppState.

Why this exists
---------------
We hit the same latent bug four times in a row: a FastAPI router referenced
`app_state.weather_engine` / `.correlator` / `.commander` / `.ws_clients`, but
`AppState.__init__` never created them. Result: those endpoints `AttributeError`
→ 500. And because the dashboard's refresh does `Promise.all(...)` over a batch
of endpoints and its fetch helper throws on any non-200, a single 500 froze
**every** page's live updates.

This test catches the class statically — no lifespan, no network, no scheduler.
If a new router lands that reads `app_state.foo`, this fails until `AppState`
defines `foo`. That stops the bug at PR time, not in production.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.main import AppState

API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
# Allowed read-only "attributes" we can't or won't put on AppState — these are
# module-level singletons or transient request-state references, not bugs.
WHITELIST: set[str] = set()


def _collect_app_state_attrs() -> dict[str, list[str]]:
    """Return {attr_name: [file:line, ...]} for every `app_state.<attr>` read."""
    pattern = re.compile(r"\bapp_state\.([A-Za-z_][A-Za-z0-9_]*)")
    seen: dict[str, list[str]] = {}
    for path in sorted(API_DIR.rglob("*.py")):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            for m in pattern.finditer(line):
                attr = m.group(1)
                seen.setdefault(attr, []).append(f"{path.name}:{lineno}")
    return seen


def test_every_referenced_app_state_attr_exists():
    """Each `app_state.X` referenced by a router must exist on AppState.

    Failure means a router will throw AttributeError → 500 in production,
    which (given the dashboard's Promise.all + throw-on-non-200 fetch helper)
    halts the entire live-refresh loop. Catching this at test time prevents
    that whole-dashboard freeze.
    """
    referenced = _collect_app_state_attrs()
    state = AppState()
    missing = {
        attr: sites
        for attr, sites in referenced.items()
        if attr not in WHITELIST and not hasattr(state, attr)
    }
    if missing:
        lines = ["AppState is missing attributes referenced by routers:"]
        for attr, sites in sorted(missing.items()):
            lines.append(f"  - app_state.{attr}  ←  {', '.join(sites)}")
        lines.append(
            "\nFix: instantiate each missing attribute in src/main.py AppState.__init__()."
        )
        raise AssertionError("\n".join(lines))
