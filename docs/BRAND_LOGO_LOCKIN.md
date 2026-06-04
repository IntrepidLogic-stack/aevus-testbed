# Aevus Logo — Lock-In Standard

**Status:** Active · **Owner:** Intrepid Logic (Woody) · **Established:** 2026-06-04

This document is the single, authoritative answer to "what is the Aevus logo, and
how do we keep it from drifting again?"

---

## 1. The canonical mark

Aevus has **one** logo. Two colors, always:

| Role | Color | Hex | Notes |
|---|---|---|---|
| Primary | Teal | `#06B6D4` | The "A" and the wordmark. Always. |
| Secondary accent | Indigo | `#6366F1` | The crossbar of the "A". |

> **Why indigo?** The original secondary was navy `#0B1020` — the *same* color as
> the dark platform background (`--bg-app: #0B1020`), so the crossbar disappeared and
> the mark looked broken. Indigo `#6366F1` contrasts and balances against **both** the
> dark dashboard and white/print report backgrounds.

### Source-of-truth files (do not duplicate — reference these)

| File | What | Use |
|---|---|---|
| `dashboard/brand/aevus-logo.svg` | Full lockup (icon + "Aevus" wordmark), `viewBox 0 0 1024 1024` | Headers, reports, marketing |
| `dashboard/brand/aevus-icon.svg` | Mark only ("A"), `viewBox 190 140 590 440` | Favicon, app icon, compact UI, loaders |
| `dashboard/favicon.svg` | Mark on a rounded navy tile | Browser tab |
| `dashboard/icons/icon-192.png` / `icon-512.png` | Maskable PWA app icons (navy bg, safe-zone padded) | Installed-app icon |
| `Graphics/Aevus_Logo_Primary.svg` | Master copy (mirror of the full lockup) | Design hand-off |

Geometry signatures (for reference): teal "A" path begins `M487.44…`; indigo crossbar
path begins `M511.32…`.

---

## 2. Usage rules

1. **Never hand-draw a new "A."** If you need the logo, embed the canonical paths or
   reference `aevus-icon.svg` / `aevus-logo.svg`. There is no "simplified" or
   "gradient" version anymore.
2. **Teal is always teal** (`#06B6D4`). The crossbar is always indigo (`#6366F1`).
   No purple gradients, no navy crossbar, no all-teal crossbar.
3. **Reports & emails** use the same mark. Every generated report header
   (`src/api/reports.py`, `award-client.js`) shows the canonical lockup.
4. **Wordmark text** ("AEVUS") may be set in Manrope with letter-spacing where an
   inline text lockup is needed — that is fine and is not a logo variant.
5. **Tagline:** "PREDICT. PREVENT. PERFORM." (period-separated, uppercase for lockups).

### Retired variants (must never return)

- Blue→purple **gradient** block-"A" (stops `#00D4FF / #1490EB / #1560C0 / #0B2252`
  legs + `#102A5C / #6D5BD0 / #9B70F6` crossbar; path `M48 0 L2 95…`).
- **Simplified** "A" (`M16 4L6 28…`, `M14 2L3 26…`).
- Wrong-glyph raster app icons (the old `icon-192.png` "H").
- Navy `#0B1020` crossbar (invisible on the platform).

---

## 3. How it's locked in (enforcement)

Three layers keep this from drifting again:

1. **Single source of truth** — the `dashboard/brand/` files above. Everything else
   references or embeds them.
2. **CI guard** — `tests/test_brand_logo.py` runs on every PR/deploy and **fails the
   build** if:
   - any canonical asset is missing,
   - any retired logo **geometry** signature (block-"A" `M48 0 L2 95…`, or the
     simplified "A" paths `M16 4L6 28…` / `M14 2L3 26…`) appears in a served
     surface (`dashboard/*.html`, authored
     `dashboard/*.js`, `src/api/reports.py`, `src/api/access_requests.py`),
   - the favicon stops using the canonical geometry,
   - the canonical icon's crossbar stops being indigo,
   - the `brand/` assets aren't in the deploy whitelist.
3. **Deploy whitelist** — `deploy.sh` ships `dashboard/brand/` (via `DASHBOARD_DIRS`),
   so the canonical files always reach production (no silent 404).

### If the guard fails

The failure message names the file and the offending signature. Replace the variant
with the canonical mark from `dashboard/brand/aevus-icon.svg` and re-run
`pytest tests/test_brand_logo.py`.

---

## 4. Scope notes

- `dashboard-staging/` and `award-recovery/` are **frozen snapshot/mirror trees**, not
  served. They are intentionally out of the guard's scope. If either is ever promoted
  back to serving, run the same replacements first.
- The marketing site (`aevus.io`, separate repo) is **not** covered here — apply the
  same canonical mark + colors there when next touched.
