"""
Aevus Testbed --- Scheduled fleet-health email digest.

Builds an email-safe (inline-table, no SVG/JS/webfonts) HTML summary of the
fleet and sends it via SES. READ-ONLY: reads asset/alert state from the DB,
never writes to any control device (IL-9000). Gated by settings.digest_enabled
and a recipient list. Mirrors the SES pattern already used in access_requests.py.

Carries a 30-day SLA & Compliance strip computed in-process from the same
logic the /api/v1/sla endpoint serves (availability, RF-margin uptime, MTBF,
MTTR, incident count) so the monthly digest reconciles with the console.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import structlog

from src.config import settings

logger = structlog.get_logger()

CT = ZoneInfo("America/Chicago")

_DOWN = ("bad", "critical", "offline")   # degraded or hard-down
_NOCOMMS = ("unknown",)                  # not reporting — surface, never treat as OK
_WATCH = ("warn", "warning")


def _esc(s: object) -> str:
    return (
        str("" if s is None else s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _status_color(status: str | None) -> str:
    s = status or ""
    if s in _DOWN:
        return "#C0392B"
    if s in _NOCOMMS:
        return "#7C5CBF"
    if s in _WATCH:
        return "#B7791F"
    if s == "good":
        return "#1E8E4E"
    return "#6B7280"


def _recipients(explicit: list[str] | None) -> list[str]:
    raw_list = explicit if explicit else [
        r.strip() for r in (getattr(settings, "digest_recipients", "") or "").split(",") if r.strip()
    ]
    # Allowlist to the org domain unless digest_allow_external is explicitly enabled.
    # Defends against an open-relay / data-exfil path even if a caller supplies recipients.
    if getattr(settings, "digest_allow_external", False):
        return [r.strip() for r in raw_list if r.strip()]
    kept, dropped = [], []
    for r in raw_list:
        r = r.strip()
        if not r:
            continue
        (kept if r.lower().endswith("@intrepidlogic.io") else dropped).append(r)
    if dropped:
        logger.warning("fleet_digest_recipients_filtered", dropped_count=len(dropped))
    return kept


def _top_alert_msg(open_by_asset: dict, asset_id: str) -> str:
    alist = open_by_asset.get(asset_id) or []
    if not alist:
        return ""
    crit = [a for a in alist if (a.severity or "") == "critical"]
    pick = crit[0] if crit else alist[0]
    return pick.message or ((pick.severity or "alert").upper())


def _sla_payload() -> dict | None:
    """Fetch the 30-day enterprise SLA summary in-process -- the SAME computation
    the /api/v1/sla endpoint serves (src.api.sla.sla_summary). Run in an isolated
    thread with its own event loop so it is safe whether or not the caller is
    already inside a running loop. Returns None on any failure so the digest still
    sends (the SLA strip is simply omitted).
    """
    try:
        import asyncio
        import concurrent.futures

        from src.api.sla import sla_summary

        # sla_summary is a FastAPI route handler whose defaults are Query(...)
        # markers; called in-process (not via a request) FastAPI never resolves
        # them, so pass explicit values or avail_target/rf_target stay Query
        # objects and the first numeric comparison raises TypeError.
        async def _call():
            return await sla_summary(from_=None, to=None, avail_target=99.9, rf_target=99.5)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(_call())).result(timeout=25)
    except Exception as e:  # noqa: BLE001
        logger.warning("fleet_digest_sla_failed", error_type=type(e).__name__)
        return None


def build_fleet_digest(db) -> tuple[str, str, str]:
    """Return (subject, html, text) for the current fleet state. Read-only."""
    assets = db.list_assets()
    alerts = db.list_alerts(limit=200)
    now_ct = datetime.now(CT)

    total = len(assets)
    healths = [a.health for a in assets if isinstance(a.health, (int, float))]
    avg_health = round(sum(healths) / len(healths)) if healths else None
    worst_health = min(healths) if healths else None

    down = [a for a in assets if a.status in _DOWN]
    nocomms = [a for a in assets if a.status in _NOCOMMS]
    watch = [a for a in assets if a.status in _WATCH]

    # Open alerts: de-dupe to the latest per (asset, message) condition; tolerate null severity.
    seen_cond: set = set()
    open_alerts = []
    for a in alerts:
        if a.status != "open":
            continue
        cond = (a.asset_id, a.message or "")
        if cond in seen_cond:
            continue
        seen_cond.add(cond)
        open_alerts.append(a)
    crit = [a for a in open_alerts if (a.severity or "") == "critical"]
    open_by_asset: dict = {}
    for a in open_alerts:
        open_by_asset.setdefault(a.asset_id, []).append(a)

    # Needs-attention = status down/no-comms/watch OR carries an open alert (closes the
    # "all nominal above a list of open alerts" contradiction). Worst-first.
    def _rank(a) -> int:
        if a.status in _DOWN:
            return 0
        if a.status in _NOCOMMS:
            return 1
        if a.id in open_by_asset and any((x.severity or "") == "critical" for x in open_by_asset[a.id]):
            return 2
        if a.status in _WATCH or a.id in open_by_asset:
            return 3
        return 9
    attn = sorted(
        [a for a in assets if a.status in (_DOWN + _NOCOMMS + _WATCH) or a.id in open_by_asset],
        key=_rank,
    )

    # Per-site rollup, grouped by the real asset location (registry `location`).
    sites: dict = {}
    for a in assets:
        s = (a.location or "Unspecified").strip() or "Unspecified"
        m = sites.setdefault(s, {"site": s, "total": 0, "down": 0, "nocomms": 0, "watch": 0})
        m["total"] += 1
        if a.status in _DOWN:
            m["down"] += 1
        elif a.status in _NOCOMMS:
            m["nocomms"] += 1
        elif a.status in _WATCH:
            m["watch"] += 1
    site_rows = sorted(sites.values(), key=lambda m: (-m["down"], -m["nocomms"], -m["watch"], -m["total"]))

    subject = (
        f"Aevus Fleet Digest, {now_ct:%a %b %-d}: "
        f"{len(down)} down, {len(nocomms)} no-comms, {len(crit)} critical alerts"
    )

    # ---- email-safe HTML (tables + inline styles; no SVG/JS/webfonts) ----
    font = "Arial,Helvetica,sans-serif"
    mono = "'Courier New',Courier,monospace"

    def kpi(label: str, value: str, color: str = "#0F1629") -> str:
        return (
            f'<td style="padding:10px 14px;border:1px solid #E2E8F0;border-radius:8px;'
            f'background:#F8FAFC;" align="center">'
            f'<div style="font-family:{mono};font-size:10px;letter-spacing:.08em;'
            f'text-transform:uppercase;color:#64748B;">{label}</div>'
            f'<div style="font-family:{font};font-size:22px;font-weight:800;color:{color};'
            f'margin-top:3px;">{value}</div></td>'
        )

    avg_txt = f"{avg_health}" if avg_health is not None else "n/a"
    worst_txt = f"{worst_health}" if worst_health is not None else "n/a"
    kpis = (
        "<table role='presentation' cellspacing='8' cellpadding='0' style='margin:4px 0 2px;'>"
        "<tr>"
        + kpi("Assets", str(total))
        + kpi("Down", str(len(down)), "#C0392B" if down else "#0F1629")
        + kpi("No-comms", str(len(nocomms)), "#7C5CBF" if nocomms else "#0F1629")
        + kpi("Watch", str(len(watch)), "#B7791F" if watch else "#0F1629")
        + kpi("Open alerts", str(len(open_alerts)), "#C0392B" if crit else "#0F1629")
        + kpi("Health (avg / worst)", f"{avg_txt} / {worst_txt}")
        + "</tr></table>"
    )

    # ---- SLA & Compliance strip (30-day, incident-derived; from /api/v1/sla) ----
    sla = _sla_payload()
    sla_section = ""
    sla_text_line = None
    if sla and isinstance(sla.get("enterprise"), dict):
        ent = sla["enterprise"]
        tgt = sla.get("targets", {})
        sla_text_line = sla.get("digest_line")

        def _pct(v) -> str:
            return f"{v:.3f}%" if isinstance(v, (int, float)) else "n/a"

        def _met_color(met, v) -> str:
            if not isinstance(v, (int, float)):
                return "#6B7280"
            return "#1E8E4E" if met else "#C0392B"

        def _dur_h(h) -> str:
            if not isinstance(h, (int, float)):
                return "n/a"
            if h >= 720:
                return f"{h / 720:.1f} mo"
            if h >= 48:
                return f"{h / 24:.1f} d"
            if h >= 1:
                return f"{h:.1f} h"
            return f"{max(1, round(h * 60))} min"

        def _dur_m(m) -> str:
            if not isinstance(m, (int, float)):
                return "n/a"
            return _dur_h(m / 60.0)

        avail_v = ent.get("availability")
        rf_v = ent.get("rf_margin_uptime")
        sla_kpis = (
            "<table role='presentation' cellspacing='8' cellpadding='0' style='margin:4px 0 2px;'><tr>"
            + kpi("Availability", _pct(avail_v), _met_color(ent.get("availability_met"), avail_v))
            + kpi("RF-margin uptime", _pct(rf_v), _met_color(ent.get("rf_met"), rf_v))
            + kpi("Incidents (30d)", str(ent.get("incidents", 0)))
            + kpi("MTBF", _dur_h(ent.get("mtbf_hours")))
            + kpi("MTTR", _dur_m(ent.get("mttr_minutes")))
            + "</tr></table>"
        )
        at = tgt.get("availability")
        rt = tgt.get("rf_margin_uptime")
        sla_caption = (
            f"Targets: availability {at}% / RF-margin uptime {rt}%. "
            "Incident-derived from the retained record: availability = share of the period free of "
            "reachability/flap incidents; RF-margin uptime = share free of path-fade (rain / obstruction) "
            "incidents. Interference incidents are counted (and drive MTBF) but do not debit these two "
            "uptime objectives."
        )
        sla_section = (
            '<div style="font-family:' + font + ';font-size:13px;font-weight:800;color:#0F1629;margin:22px 0 8px;">'
            'SLA &amp; Compliance '
            '<span style="font-weight:600;color:#64748B;font-size:11px;">last 30 days</span></div>'
            + sla_kpis
            + '<div style="font-family:' + font + ';font-size:11px;color:#94A3B8;line-height:1.5;margin-top:6px;">'
            + _esc(sla_caption) + "</div>"
        )

    site_body = ""
    for m in site_rows:
        if m["down"]:
            st, stc = "DEGRADED", "#C0392B"
        elif m["nocomms"]:
            st, stc = "NO-COMMS", "#7C5CBF"
        elif m["watch"]:
            st, stc = "WATCH", "#B7791F"
        else:
            st, stc = "OK", "#1E8E4E"
        site_body += (
            f'<tr><td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;">{_esc(m["site"])}</td>'
            f'<td align="center" style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-family:{mono};">{m["total"]}</td>'
            f'<td align="center" style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-family:{mono};color:#C0392B;">{m["down"] or ""}</td>'
            f'<td align="center" style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-family:{mono};color:#7C5CBF;">{m["nocomms"] or ""}</td>'
            f'<td align="center" style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-family:{mono};color:#B7791F;">{m["watch"] or ""}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-weight:700;color:{stc};">{st}</td></tr>'
        )

    if attn:
        attn_body = ""
        for a in attn:
            c = _status_color(a.status)
            reason = _top_alert_msg(open_by_asset, a.id) or ("loss of contact" if a.status in _NOCOMMS else "status " + (a.status or "?"))
            hv = a.health if isinstance(a.health, (int, float)) else "n/a"
            attn_body += (
                f'<tr><td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-weight:600;">{_esc(a.name)} '
                f'<span style="font-family:{mono};font-size:10px;color:#94A3B8;">{_esc(a.id)}</span></td>'
                f'<td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;">{_esc(a.location or "n/a")}</td>'
                f'<td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-weight:700;color:{c};">{_esc((a.status or "?").upper())}</td>'
                f'<td align="center" style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-family:{mono};color:{c};">{hv}</td>'
                f'<td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;color:#475569;">{_esc(reason)}</td></tr>'
            )
        attn_section = (
            '<div style="font-family:' + font + ';font-size:13px;font-weight:800;color:#0F1629;margin:22px 0 8px;">Needs attention</div>'
            '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="border:1px solid #E2E8F0;border-radius:8px;border-collapse:separate;overflow:hidden;font-family:' + font + ';font-size:12.5px;color:#0F1629;">'
            '<tr style="background:#F1F5F9;"><td style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Asset</td>'
            '<td style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Site</td>'
            '<td style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Status</td>'
            '<td align="center" style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Health</td>'
            '<td style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Reason</td></tr>'
            + attn_body + "</table>"
        )
    else:
        attn_section = (
            '<div style="font-family:' + font + ';font-size:13px;color:#1E8E4E;font-weight:700;margin:22px 0 8px;">'
            'All assets nominal; no open alerts.</div>'
        )

    alert_section = ""
    if open_alerts:
        rows = ""
        for a in open_alerts[:12]:
            sev = (a.severity or "info")
            sc = "#C0392B" if sev == "critical" else ("#B7791F" if sev == "warning" else "#0E7490")
            det = ""
            if a.detected_at:
                dt = a.detected_at if a.detected_at.tzinfo else a.detected_at.replace(tzinfo=UTC)
                det = dt.astimezone(CT).strftime("%b %-d %H:%M")
            rows += (
                f'<tr><td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-weight:700;color:{sc};">{_esc(sev.upper())}</td>'
                f'<td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;">{_esc(a.asset_name or a.asset_id)}</td>'
                f'<td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;color:#475569;">{_esc(a.message or "")}</td>'
                f'<td style="padding:6px 10px;border-bottom:1px solid #EEF2F7;font-family:{mono};font-size:11px;color:#94A3B8;white-space:nowrap;">{det}</td></tr>'
            )
        more = f'<div style="font-size:11px;color:#94A3B8;margin-top:6px;">plus {len(open_alerts) - 12} more open</div>' if len(open_alerts) > 12 else ""
        alert_section = (
            '<div style="font-family:' + font + ';font-size:13px;font-weight:800;color:#0F1629;margin:22px 0 8px;">Open alerts</div>'
            '<table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="border:1px solid #E2E8F0;border-radius:8px;border-collapse:separate;overflow:hidden;font-family:' + font + ';font-size:12.5px;color:#0F1629;">'
            + rows + "</table>" + more
        )

    html = f"""<!doctype html><html><body style="margin:0;padding:0;background:#EEF2F7;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#EEF2F7;padding:24px 0;">
<tr><td align="center">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="width:640px;max-width:640px;background:#FFFFFF;border-radius:14px;overflow:hidden;box-shadow:0 2px 10px rgba(15,22,41,.08);">
  <tr><td style="background:#0B1020;padding:20px 26px;">
    <span style="font-family:{mono};font-weight:700;letter-spacing:.2em;font-size:15px;color:#FFFFFF;">AEVUS</span>
    <span style="font-family:{mono};font-weight:700;letter-spacing:.2em;font-size:15px;color:#38BDF8;margin-left:6px;">COMMS</span>
    <div style="font-family:{font};font-size:18px;font-weight:800;color:#FFFFFF;margin-top:10px;">Fleet Health Digest</div>
    <div style="font-family:{mono};font-size:11px;color:#8A94A9;margin-top:3px;">{now_ct:%A, %B %-d, %Y %-I:%M %p %Z} · read-only snapshot</div>
  </td></tr>
  <tr><td style="padding:22px 26px 10px;">
    {kpis}
    {sla_section}
    <div style="font-family:{font};font-size:13px;font-weight:800;color:#0F1629;margin:22px 0 8px;">By location</div>
    <table role="presentation" cellspacing="0" cellpadding="0" width="100%" style="border:1px solid #E2E8F0;border-radius:8px;border-collapse:separate;overflow:hidden;font-family:{font};font-size:12.5px;color:#0F1629;">
      <tr style="background:#F1F5F9;"><td style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Location</td>
      <td align="center" style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Assets</td>
      <td align="center" style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Down</td>
      <td align="center" style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">No-comms</td>
      <td align="center" style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Watch</td>
      <td style="padding:7px 10px;font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:#64748B;">Status</td></tr>
      {site_body}
    </table>
    {attn_section}
    {alert_section}
  </td></tr>
  <tr><td style="padding:16px 26px 24px;">
    <a href="https://aevus.intrepidlogic.io/comms/Aevus_Comms_Console.html" style="display:inline-block;background:#0EA5E9;color:#06121F;font-family:{font};font-size:13px;font-weight:700;text-decoration:none;padding:10px 22px;border-radius:8px;">Open the live console</a>
    <div style="font-family:{font};font-size:11px;color:#94A3B8;line-height:1.5;margin-top:16px;">
      Aevus Comms · Intrepid Logic LLC (SDVOSB) · automated read-only fleet digest. Health is a composite
      index (comm reliability, vital compliance, predictive, maintenance); status and health are rolling/modeled
      values. This message never writes to any control device (IL-9000). Reply to adjust recipients or cadence.
    </div>
  </td></tr>
</table>
</td></tr></table></body></html>"""

    # plain-text fallback
    tlines = [
        "AEVUS COMMS, Fleet Health Digest",
        f"{now_ct:%A %B %-d %Y %-I:%M %p %Z} (read-only snapshot)",
        "",
        f"Assets: {total} | Down: {len(down)} | No-comms: {len(nocomms)} | Watch: {len(watch)} "
        f"| Open alerts: {len(open_alerts)} | Avg health: {avg_txt} | Worst: {worst_txt}",
    ]
    if sla_text_line:
        tlines += ["", sla_text_line]
    tlines += ["", "By location:"]
    for m in site_rows:
        st = "DEGRADED" if m["down"] else ("NO-COMMS" if m["nocomms"] else ("WATCH" if m["watch"] else "OK"))
        tlines.append(f"  - {m['site']}: {m['total']} assets, {m['down']} down, {m['nocomms']} no-comms, {m['watch']} watch [{st}]")
    if attn:
        tlines += ["", "Needs attention:"]
        for a in attn:
            reason = _top_alert_msg(open_by_asset, a.id) or ("loss of contact" if a.status in _NOCOMMS else "status " + (a.status or "?"))
            hv = a.health if isinstance(a.health, (int, float)) else "n/a"
            tlines.append(f"  - {a.name} ({a.id}) @ {a.location or 'n/a'}: {(a.status or '?').upper()} health {hv} :: {reason}")
    if open_alerts:
        tlines += ["", "Open alerts:"]
        for a in open_alerts[:12]:
            tlines.append(f"  - [{(a.severity or 'info').upper()}] {a.asset_name or a.asset_id}: {a.message or ''}")
    tlines += ["", "Open the live console: https://aevus.intrepidlogic.io/comms/Aevus_Comms_Console.html"]
    text = "\n".join(tlines)

    return subject, html, text


def send_fleet_digest(db, recipients: list[str] | None = None) -> dict:
    """Build and send the digest via SES. Returns a status dict; never raises.
    Recipients are allowlisted to @intrepidlogic.io unless settings.digest_allow_external."""
    recips = _recipients(recipients)
    if not recips:
        logger.info("fleet_digest_skipped", reason="no_allowed_recipients")
        return {"status": "skipped", "reason": "no allowed recipients"}
    try:
        subject, html, text = build_fleet_digest(db)
        import boto3

        ses = boto3.client("sesv2", region_name=getattr(settings, "aws_region", "us-east-1"))
        ses.send_email(
            FromEmailAddress=getattr(settings, "ses_sender", "Aevus Comms <info@intrepidlogic.io>"),
            Destination={"ToAddresses": recips},
            Content={
                "Simple": {
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html, "Charset": "UTF-8"},
                        "Text": {"Data": text, "Charset": "UTF-8"},
                    },
                }
            },
        )
        logger.info("fleet_digest_sent", recipient_count=len(recips), subject=subject)
        return {"status": "sent", "recipient_count": len(recips), "subject": subject, "generated_at": datetime.now(UTC).isoformat()}
    except Exception as e:  # noqa: BLE001
        logger.warning("fleet_digest_failed", error_type=type(e).__name__)
        return {"status": "error", "error": "send failed; see server logs"}
