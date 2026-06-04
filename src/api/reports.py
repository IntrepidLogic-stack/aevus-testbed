import math
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/reports", tags=["reports"])


# ──────────────────────────────────────────────────────────────────────────
# JSON reports (Task #154 — restored from test contract that predates the
# current src/api/reports.py file; tests/test_reports.py expected these
# endpoints since before PR #56 caught the gap)
# ──────────────────────────────────────────────────────────────────────────
@router.get("/fleet-health")
async def fleet_health_report(hours: int = Query(24, ge=1, le=720)):
    """Fleet health snapshot for the trailing `hours` window.

    Shape matches tests/test_reports.py contract:
      { report: "fleet-health", generated_at, period_hours, total_assets,
        assets: [{id, name, status, health, ...}] }
    """
    from src.main import app_state

    assets = app_state.db.list_assets()
    asset_records = [
        {
            "id": a.id,
            "name": a.name,
            "type": a.type,
            "status": a.status,
            "health": a.health,
            "vendor": a.vendor,
            "model": a.model,
            "location": a.location,
        }
        for a in assets
    ]
    by_status: dict[str, int] = {}
    for a in assets:
        by_status[a.status] = by_status.get(a.status, 0) + 1

    healths = [a.health for a in assets if a.health is not None]
    avg_health = round(sum(healths) / len(healths)) if healths else None

    return {
        "report": "fleet-health",
        "generated_at": datetime.now(UTC).isoformat(),
        "period_hours": hours,
        "total_assets": len(assets),
        "average_health": avg_health,
        "by_status": by_status,
        "assets": asset_records,
    }


@router.get("/alerts")
async def alert_history_report(
    hours: int = Query(168, ge=1, le=8760),
    severity: str | None = Query(None, pattern="^(critical|warning|info)$"),
):
    """Alert history for the trailing `hours` window, optional severity filter.

    Shape matches tests/test_reports.py contract:
      { report: "alert-history", generated_at, period_hours, total_alerts,
        severity_filter, alerts: [...] }
    """
    from src.main import app_state

    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    raw = app_state.db.list_alerts(limit=1000)
    in_window = [a for a in raw if a.detected_at >= cutoff and (severity is None or a.severity == severity)]
    return {
        "report": "alert-history",
        "generated_at": datetime.now(UTC).isoformat(),
        "period_hours": hours,
        "severity_filter": severity,
        "total_alerts": len(in_window),
        "alerts": [
            {
                "id": a.id,
                "severity": a.severity,
                "asset_id": a.asset_id,
                "asset_name": a.asset_name,
                "message": a.message,
                "detected_at": a.detected_at.isoformat(),
                "status": a.status,
            }
            for a in in_window
        ],
    }


@router.get("/site-summary", response_class=HTMLResponse)
async def site_summary_report():
    from src.main import app_state

    db = app_state.db

    assets = db.list_assets()
    alerts = db.list_alerts(limit=30)
    now = datetime.now(UTC)

    # KPIs
    total = len(assets)
    online = sum(1 for a in assets if a.status in ("good", "warn", "warning"))
    healths = [a.health for a in assets if a.health is not None]
    avg_health = round(sum(healths) / len(healths)) if healths else 0
    sum(1 for a in alerts if a.severity == "critical" and a.status == "open")
    sum(1 for a in alerts if a.severity == "warning" and a.status == "open")
    total_open = sum(1 for a in alerts if a.status == "open")

    # Status counts for donut
    good_count = sum(1 for a in assets if a.status == "good")
    warn_count = sum(1 for a in assets if a.status in ("warn", "warning"))
    bad_count = sum(1 for a in assets if a.status in ("bad", "critical"))
    offline_count = total - good_count - warn_count - bad_count

    # Health bar chart SVG
    bar_h = 28
    bar_gap = 6
    bar_chart_h = total * (bar_h + bar_gap) + 20
    bars_svg = ""
    for i, a in enumerate(sorted(assets, key=lambda x: x.health or 0, reverse=True)):
        h = a.health or 0
        color = (
            "#10D478"
            if a.status == "good"
            else "#FBBF24"
            if a.status in ("warn", "warning")
            else "#EF4444"
            if a.status in ("bad", "critical")
            else "#6B7280"
        )
        y = i * (bar_h + bar_gap)
        bw = max(2, h / 100 * 400)
        bars_svg += f'<text x="0" y="{y + 18}" fill="#333" font-size="11" font-family="Manrope" font-weight="600">{a.name}</text>'
        bars_svg += f'<text x="0" y="{y + 28}" fill="#999" font-size="8" font-family="monospace">{a.id}</text>'
        bars_svg += f'<rect x="160" y="{y + 4}" width="{bw}" height="20" rx="4" fill="{color}"/>'
        bars_svg += f'<text x="{160 + bw + 8}" y="{y + 18}" fill="#333" font-size="12" font-weight="700" font-family="monospace">{h}</text>'

    # Donut chart SVG
    def donut_arc(cx, cy, r, start_angle, end_angle, color):
        if end_angle - start_angle >= 2 * math.pi - 0.01:
            return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="20"/>'
        x1 = cx + r * math.cos(start_angle)
        y1 = cy + r * math.sin(start_angle)
        x2 = cx + r * math.cos(end_angle)
        y2 = cy + r * math.sin(end_angle)
        large = 1 if (end_angle - start_angle) > math.pi else 0
        return f'<path d="M{x1:.1f},{y1:.1f} A{r},{r} 0 {large} 1 {x2:.1f},{y2:.1f}" fill="none" stroke="{color}" stroke-width="20" stroke-linecap="round"/>'

    donut_svg = ""
    segments = [
        (good_count, "#10D478", "Good"),
        (warn_count, "#FBBF24", "Warning"),
        (bad_count, "#EF4444", "Critical"),
        (offline_count, "#6B7280", "Offline"),
    ]
    segments = [(c, col, lbl) for c, col, lbl in segments if c > 0]
    angle = -math.pi / 2
    for count, color, _label in segments:
        sweep = (count / total) * 2 * math.pi if total > 0 else 0
        if sweep > 0:
            donut_svg += donut_arc(80, 80, 55, angle, angle + sweep - 0.05, color)
            angle += sweep

    legend_svg = ""
    for i, (count, color, label) in enumerate(segments):
        ly = 40 + i * 22
        legend_svg += f'<rect x="180" y="{ly}" width="10" height="10" rx="2" fill="{color}"/>'
        legend_svg += (
            f'<text x="196" y="{ly + 9}" fill="#333" font-size="11" font-family="Manrope">{label}: {count}</text>'
        )

    # Vitals summary
    vitals_html = ""
    for a in assets:
        if not a.vitals:
            continue
        vitals_html += f'<tr style="background:#f0f4f8;"><td colspan="4" style="font-weight:700;padding:8px 12px;">{a.name} ({a.id})</td></tr>'
        for v in a.vitals[:8]:
            sc = (
                "#10D478"
                if v.status == "good"
                else "#FBBF24"
                if v.status in ("warn", "warning")
                else "#EF4444"
                if v.status in ("bad", "critical")
                else "#666"
            )
            vitals_html += f'<tr><td style="padding:4px 12px;">{v.label}</td><td style="font-family:monospace;font-weight:600;padding:4px 8px;">{v.value}</td><td style="color:#999;">{v.unit}</td><td><span style="color:{sc};">●</span> {v.status or "—"}</td></tr>'

    # Asset table
    asset_rows = ""
    for a in assets:
        sc = (
            "#10D478"
            if a.status == "good"
            else "#FBBF24"
            if a.status in ("warn", "warning")
            else "#EF4444"
            if a.status in ("bad", "critical")
            else "#6B7280"
        )
        asset_rows += f"""<tr>
            <td style="font-weight:600;">{a.name}</td><td style="font-family:monospace;">{a.id}</td>
            <td>{a.type or ""}</td><td>{a.vendor or ""} {a.model or ""}</td>
            <td style="font-family:monospace;">{a.ip_address or ""}</td>
            <td><span style="color:{sc};font-weight:700;">● {a.status or "?"}</span></td>
            <td style="font-family:monospace;font-weight:700;color:{sc};">{a.health if a.health is not None else "—"}</td></tr>"""

    # Alert rows
    alert_rows = ""
    for a in alerts[:20]:
        sc = "#EF4444" if a.severity == "critical" else "#FBBF24" if a.severity == "warning" else "#06B6D4"
        det = a.detected_at.strftime("%Y-%m-%d %H:%M") if a.detected_at else ""
        alert_rows += f"""<tr>
            <td><span style="color:{sc};font-weight:700;">{a.severity.upper()}</span></td>
            <td>{a.asset_name or a.asset_id}</td><td>{a.message or ""}</td>
            <td style="font-family:monospace;font-size:11px;">{det}</td>
            <td>{a.status or ""}</td></tr>"""

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Aevus Site Report — Killdeer Field</title>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:Manrope,sans-serif;color:#1a1a2e;background:#fff;padding:32px;max-width:900px;margin:0 auto;font-size:12px;}}
h1{{font-size:22px;font-weight:700;}}
h2{{font-size:15px;font-weight:700;color:#1a1a2e;margin:24px 0 12px;border-bottom:2px solid #06B6D4;padding-bottom:6px;}}
.header{{display:flex;justify-content:space-between;align-items:center;border-bottom:3px solid #06B6D4;padding-bottom:16px;margin-bottom:24px;}}
.logo-mark{{display:flex;align-items:center;gap:12px;}}
.tagline{{font-size:9px;letter-spacing:2px;color:#7B8499;font-family:monospace;margin-top:4px;}}
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;}}
.kpi{{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:12px;text-align:center;}}
.kpi-val{{font-size:28px;font-weight:700;font-family:monospace;}}
.kpi-label{{font-size:9px;text-transform:uppercase;letter-spacing:1px;color:#7B8499;margin-top:4px;}}
table{{width:100%;border-collapse:collapse;font-size:11px;}}
th{{background:#f0f4f8;padding:8px;text-align:left;font-size:9px;text-transform:uppercase;letter-spacing:0.5px;color:#7B8499;}}
td{{padding:6px 8px;border-bottom:1px solid #f0f4f8;}}
.charts-row{{display:grid;grid-template-columns:2fr 1fr;gap:24px;margin-bottom:24px;}}
.footer{{text-align:center;margin-top:32px;padding-top:16px;border-top:1px solid #e2e8f0;color:#7B8499;font-size:10px;}}
@media print{{
  body{{padding:16px;}}
  .kpi{{print-color-adjust:exact;-webkit-print-color-adjust:exact;}}
  svg{{print-color-adjust:exact;-webkit-print-color-adjust:exact;}}
  table{{page-break-inside:auto;}}
  tr{{page-break-inside:avoid;}}
  h2{{page-break-after:avoid;}}
}}
</style></head><body>

<div class="header">
  <div class="logo-mark">
    <!-- Canonical Aevus mark — single source: /dashboard/brand/aevus-icon.svg (docs/BRAND_LOGO_LOCKIN.md) -->
    <svg viewBox="150 110 670 500" width="48" height="36"><rect x="150" y="110" width="670" height="500" rx="90" fill="#0B1020"/><path fill="#06b6d4" d="M487.44,154.66c10.46-4.08,24.78-1.69,36.06-2.31,4.74-.26,12.18-.14,16.76.47,3.7.48,7.31,1.49,10.72,2.99,5.33,2.39,9.97,6.09,13.49,10.74,3.82,4.97,12.72,23.25,15.96,29.94,4.54,9.37,11.98,22.39,15.89,31.45,3.46,6.57,6.9,13.35,10.19,20.02,22.69,45.91,46.99,91.36,69.13,137.52l-54.16.03c-47.07.05-40.06,1.97-61.26-40.55l-24.62-49.05c-5.47-10.93-11.17-22.96-16.98-33.55l-99.6,199.06-24,48.21c-4.73,9.53-15.11,33.59-21.58,40.09-3.73,3.73-7.79,5.98-12.96,7.08-9.93,2.12-22.72.89-32.91.89l-55.33-.04c6.92-15.9,18.4-37.39,26.3-53.26l53.2-106.42,81.39-160.83c10.86-21.02,21.74-42.03,32.68-63.01,4.66-8.94,11.7-16.59,21.66-19.47Z"/><path fill="#6366f1" d="M511.32,414.05c47.71-1.69,93.76.15,140.41-.7,25.11-1.16,40.33,1.6,51.03,26.81,19.12,38.52,39.61,76.78,58.21,114.48,1.64,5.09-5.72,2.33-9.89,3.04-18.94.02-35.99-.06-51.35.2-8.83.11-19.09.79-27.19-2.97-15.85-8.98-18.9-25.07-30.04-43.89-4.65-6.71-11.13-28.17-17.11-28.89-54.24-.39-110.5.43-164.82,0-4.63-.17-4.18-1.93-2.04-5.83,14.56-21.76,22.41-58.69,52.78-62.25Z"/></svg>
    <div><h1>AEVUS</h1><div class="tagline">PREDICT. PREVENT. PERFORM.</div></div>
  </div>
  <div style="text-align:right;">
    <div style="font-weight:700;">Killdeer Field</div>
    <div style="font-size:10px;color:#7B8499;">10102 Clydesdale Dr, Needville, TX 77461</div>
    <div style="font-size:10px;color:#7B8499;margin-top:4px;">{now.strftime("%B %d, %Y %H:%M UTC")}</div>
  </div>
</div>

<div class="kpi-row">
  <div class="kpi"><div class="kpi-val">{total}</div><div class="kpi-label">Assets Monitored</div></div>
  <div class="kpi"><div class="kpi-val" style="color:{"#10D478" if avg_health >= 80 else "#FBBF24" if avg_health >= 50 else "#EF4444"};">{avg_health}</div><div class="kpi-label">Avg Health Score</div></div>
  <div class="kpi"><div class="kpi-val">{online}</div><div class="kpi-label">Online</div></div>
  <div class="kpi"><div class="kpi-val" style="color:{"#EF4444" if total_open > 0 else "#10D478"};">{total_open}</div><div class="kpi-label">Active Alerts</div></div>
</div>

<div class="charts-row">
  <div>
    <h2>Fleet Health Scores</h2>
    <svg viewBox="0 0 500 {bar_chart_h}" width="100%" style="max-height:300px;">{bars_svg}</svg>
  </div>
  <div>
    <h2>Status Distribution</h2>
    <svg viewBox="0 0 280 170" width="100%">
      {donut_svg}
      <text x="80" y="78" fill="#333" font-size="22" font-weight="700" text-anchor="middle" font-family="monospace">{total}</text>
      <text x="80" y="94" fill="#999" font-size="9" text-anchor="middle">TOTAL</text>
      {legend_svg}
    </svg>
  </div>
</div>

<h2>Asset Inventory</h2>
<table><thead><tr><th>Name</th><th>ID</th><th>Type</th><th>Model</th><th>IP</th><th>Status</th><th>Health</th></tr></thead>
<tbody>{asset_rows}</tbody></table>

<h2>Key Vitals by Asset</h2>
<table><thead><tr><th>Metric</th><th>Value</th><th>Unit</th><th>Status</th></tr></thead>
<tbody>{vitals_html}</tbody></table>

<h2>Alarm History</h2>
<table><thead><tr><th>Severity</th><th>Asset</th><th>Message</th><th>Detected</th><th>Status</th></tr></thead>
<tbody>{alert_rows if alert_rows else "<tr><td colspan='5' style='text-align:center;color:#999;padding:16px;'>No alerts</td></tr>"}</tbody></table>

<div class="footer">
  <div>SDVOSB — Intrepid Logic LLC · Service-Disabled Veteran-Owned Small Business</div>
  <div style="margin-top:4px;">Generated by Aevus · {now.strftime("%Y-%m-%d %H:%M:%S UTC")}</div>
</div>
</body></html>"""
    return HTMLResponse(content=html)
