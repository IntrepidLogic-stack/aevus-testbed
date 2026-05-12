from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from datetime import datetime

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/site-summary")
async def site_summary_report():
    """Generate a printable HTML site summary report."""
    from src.main import app_state
    db = app_state.db

    assets = db.list_assets()
    alerts = db.list_alerts(limit=20)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S CT")
    total = len(assets)
    online = sum(1 for a in assets if a.status == "good")
    avg_health = round(sum(a.health or 0 for a in assets) / max(total, 1), 1)
    critical_alarms = sum(1 for a in alerts if a.severity == "critical" and a.status == "open")
    warning_alarms = sum(1 for a in alerts if a.severity == "warning" and a.status == "open")

    asset_rows = ""
    for a in assets:
        h = a.health or 0
        hcol = "#10D478" if h > 80 else "#FBBF24" if h > 50 else "#EF4444"
        asset_rows += f"""<tr>
          <td style="font-weight:600;color:#06B6D4;">{a.id}</td>
          <td>{a.name}</td><td>{a.type}</td><td>{a.protocol}</td><td>{a.ip_address or ""}</td>
          <td style="color:{hcol};font-weight:600;">{h}%</td>
          <td style="color:#10D478;">\u25cf {a.status}</td></tr>"""

    alarm_rows = ""
    for al in alerts[:10]:
        scol = "#EF4444" if al.severity == "critical" else "#FBBF24" if al.severity == "warning" else "#10D478"
        alarm_rows += f"""<tr>
          <td>{al.detected_at}</td><td>{al.asset_id}</td>
          <td style="color:{scol};font-weight:600;">{al.severity}</td>
          <td>{al.message}</td><td>{al.status}</td></tr>"""

    if not alarm_rows:
        alarm_rows = '<tr><td colspan="5" style="text-align:center;color:#7B8499;padding:20px;">No alarms recorded</td></tr>'

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Aevus Site Report</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:'Manrope',sans-serif;background:#0B1020;color:#FFF;padding:40px}}
  .report{{max-width:1000px;margin:0 auto}}
  .header{{display:flex;justify-content:space-between;margin-bottom:32px;padding-bottom:20px;border-bottom:2px solid #06B6D4}}
  .logo{{font-family:'JetBrains Mono',monospace;font-size:28px;font-weight:700;color:#06B6D4;letter-spacing:3px}}
  .tagline{{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:2px;color:#7B8499;margin-top:4px}}
  .meta{{text-align:right;font-size:12px;color:#B4BCD0}}
  .stitle{{font-size:16px;font-weight:700;color:#06B6D4;margin:28px 0 12px;letter-spacing:1px;text-transform:uppercase}}
  .kpi-row{{display:flex;gap:16px;margin-bottom:24px}}
  .kpi{{flex:1;background:#161E33;border:1px solid rgba(148,163,184,0.12);border-radius:12px;padding:16px;text-align:center}}
  .kpi-val{{font-size:28px;font-weight:700;font-family:'JetBrains Mono',monospace}}
  .kpi-label{{font-size:10px;color:#7B8499;text-transform:uppercase;letter-spacing:1px;margin-top:4px}}
  table{{width:100%;border-collapse:collapse;font-size:12px}}
  th{{text-align:left;padding:8px 12px;color:#7B8499;font-size:10px;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid rgba(148,163,184,0.15)}}
  td{{padding:8px 12px;border-bottom:1px solid rgba(148,163,184,0.06)}}
  .footer{{margin-top:40px;padding-top:16px;border-top:1px solid rgba(148,163,184,0.1);display:flex;justify-content:space-between;font-size:10px;color:#7B8499}}
  @media print{{body{{background:#fff;color:#000}}.kpi{{border:1px solid #ddd}}th{{color:#666}}td{{border-bottom:1px solid #eee}}}}
</style></head><body>
<div class="report">
  <div class="header"><div><div class="logo">AEVUS</div><div class="tagline">PREDICT. PREVENT. PERFORM.</div></div>
  <div class="meta"><div style="font-weight:600;font-size:14px">Site Health Report</div><div>Killdeer Field — Needville, TX 77461</div><div>Generated: {now}</div></div></div>
  <div class="stitle">Site Overview</div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-val">{total}</div><div class="kpi-label">Assets Monitored</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#10D478">{online}</div><div class="kpi-label">Online</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#06B6D4">{avg_health}%</div><div class="kpi-label">Avg Health</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#EF4444">{critical_alarms}</div><div class="kpi-label">Critical Alarms</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#FBBF24">{warning_alarms}</div><div class="kpi-label">Warnings</div></div>
  </div>
  <div class="stitle">Asset Inventory</div>
  <table><thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Protocol</th><th>IP</th><th>Health</th><th>Status</th></tr></thead><tbody>{asset_rows}</tbody></table>
  <div class="stitle">Alarm History</div>
  <table><thead><tr><th>Time</th><th>Asset</th><th>Severity</th><th>Message</th><th>Status</th></tr></thead><tbody>{alarm_rows}</tbody></table>
  <div class="footer"><div>Aevus Platform v2.4.1 · Intrepid Logic LLC · SDVOSB</div><div>CONFIDENTIAL — For authorized personnel only</div></div>
</div></body></html>"""
    return HTMLResponse(content=html)
