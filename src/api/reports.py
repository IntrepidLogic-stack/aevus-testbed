from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from datetime import datetime
import json

router = APIRouter(prefix="/reports", tags=["reports"])

@router.get("/site-summary")
async def site_summary_report():
    """Generate a printable HTML site summary report."""
    from src.storage.sqlite_db import get_db
    db = get_db()

    # Get all assets
    assets = db.execute("SELECT * FROM assets ORDER BY id").fetchall()
    asset_list = [dict(a) for a in assets]

    # Get recent alarms
    alarms = []
    try:
        alarm_rows = db.execute("SELECT * FROM alarms ORDER BY timestamp DESC LIMIT 20").fetchall()
        alarms = [dict(a) for a in alarm_rows]
    except:
        pass

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S CT")
    total = len(asset_list)
    online = sum(1 for a in asset_list if a.get("status") == "good")
    avg_health = round(sum(a.get("health", 0) for a in asset_list) / max(total, 1), 1)
    critical_alarms = sum(1 for a in alarms if a.get("severity") == "critical" and a.get("state") == "active")
    warning_alarms = sum(1 for a in alarms if a.get("severity") == "warning" and a.get("state") == "active")

    asset_rows = ""
    for a in asset_list:
        h = a.get("health", 0)
        hcol = "#10D478" if h > 80 else "#FBBF24" if h > 50 else "#EF4444"
        asset_rows += f"""<tr>
          <td style="font-weight:600;color:#06B6D4;">{a.get("id","")}</td>
          <td>{a.get("name","")}</td>
          <td>{a.get("type","")}</td>
          <td>{a.get("protocol","")}</td>
          <td>{a.get("ip","")}</td>
          <td style="color:{hcol};font-weight:600;">{h}%</td>
          <td style="color:#10D478;">● {a.get("status","")}</td>
        </tr>"""

    alarm_rows = ""
    for al in alarms[:10]:
        scol = "#EF4444" if al.get("severity") == "critical" else "#FBBF24" if al.get("severity") == "warning" else "#10D478"
        alarm_rows += f"""<tr>
          <td>{al.get("timestamp","")}</td>
          <td>{al.get("asset_id","")}</td>
          <td style="color:{scol};font-weight:600;">{al.get("severity","")}</td>
          <td>{al.get("metric", al.get("message",""))}</td>
          <td>{al.get("state","")}</td>
        </tr>"""

    if not alarm_rows:
        alarm_rows = '<tr><td colspan="5" style="text-align:center;color:#7B8499;padding:20px;">No alarms recorded</td></tr>'

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Aevus Site Report — Killdeer Field</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Manrope',sans-serif; background:#0B1020; color:#FFFFFF; padding:40px; }}
  .report {{ max-width:1000px; margin:0 auto; }}
  .header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:32px; padding-bottom:20px; border-bottom:2px solid #06B6D4; }}
  .logo {{ font-family:'JetBrains Mono',monospace; font-size:28px; font-weight:700; color:#06B6D4; letter-spacing:3px; }}
  .tagline {{ font-family:'JetBrains Mono',monospace; font-size:9px; letter-spacing:2px; color:#7B8499; margin-top:4px; }}
  .report-meta {{ text-align:right; font-size:12px; color:#B4BCD0; }}
  .section-title {{ font-size:16px; font-weight:700; color:#06B6D4; margin:28px 0 12px; letter-spacing:1px; text-transform:uppercase; }}
  .kpi-row {{ display:flex; gap:16px; margin-bottom:24px; }}
  .kpi {{ flex:1; background:#161E33; border:1px solid rgba(148,163,184,0.12); border-radius:12px; padding:16px; text-align:center; }}
  .kpi-val {{ font-size:28px; font-weight:700; font-family:'JetBrains Mono',monospace; }}
  .kpi-label {{ font-size:10px; color:#7B8499; text-transform:uppercase; letter-spacing:1px; margin-top:4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th {{ text-align:left; padding:8px 12px; color:#7B8499; font-size:10px; text-transform:uppercase; letter-spacing:0.5px; border-bottom:1px solid rgba(148,163,184,0.15); }}
  td {{ padding:8px 12px; border-bottom:1px solid rgba(148,163,184,0.06); }}
  .footer {{ margin-top:40px; padding-top:16px; border-top:1px solid rgba(148,163,184,0.1); display:flex; justify-content:space-between; font-size:10px; color:#7B8499; }}
  @media print {{
    body {{ background:white; color:black; }}
    .kpi {{ border:1px solid #ddd; }}
    th {{ color:#666; }}
    td {{ border-bottom:1px solid #eee; }}
  }}
</style>
</head>
<body>
<div class="report">
  <div class="header">
    <div>
      <div class="logo">AEVUS</div>
      <div class="tagline">PREDICT. PREVENT. PERFORM.</div>
    </div>
    <div class="report-meta">
      <div style="font-weight:600;font-size:14px;">Site Health Report</div>
      <div>Killdeer Field — Needville, TX 77461</div>
      <div>Generated: {now}</div>
    </div>
  </div>

  <div class="section-title">Site Overview</div>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-val">{total}</div><div class="kpi-label">Assets Monitored</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#10D478;">{online}</div><div class="kpi-label">Online</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#06B6D4;">{avg_health}%</div><div class="kpi-label">Avg Health</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#EF4444;">{critical_alarms}</div><div class="kpi-label">Critical Alarms</div></div>
    <div class="kpi"><div class="kpi-val" style="color:#FBBF24;">{warning_alarms}</div><div class="kpi-label">Warnings</div></div>
  </div>

  <div class="section-title">Asset Inventory</div>
  <table>
    <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Protocol</th><th>IP Address</th><th>Health</th><th>Status</th></tr></thead>
    <tbody>{asset_rows}</tbody>
  </table>

  <div class="section-title">Alarm History (Last 10)</div>
  <table>
    <thead><tr><th>Timestamp</th><th>Asset</th><th>Severity</th><th>Metric</th><th>State</th></tr></thead>
    <tbody>{alarm_rows}</tbody>
  </table>

  <div class="footer">
    <div>Aevus Platform v2.4.1 · Intrepid Logic LLC · SDVOSB</div>
    <div>CONFIDENTIAL — For authorized personnel only</div>
  </div>
</div>
</body>
</html>"""
    return HTMLResponse(content=html)
