"""
Aevus — Notification Engine
Sends alerts via AWS SES (email) and AWS SNS (SMS).

ISA-18.2 discipline applied to our OWN alerts (Task #201). The platform
that sells alarm rationalization must not flood its own operator's inbox.
Three defenses layer on top of the AlertEngine's chattering detection:

  1. SEVERITY GATE — email fires for CRITICAL only. WARNING-level alerts
     accumulate into a periodic digest (see flush_warning_digest), never
     a per-alert email. This alone kills the warning flood.
  2. CONDITION-KEYED DEDUP — the rate limit keys on (asset_id, metric,
     severity), NOT the alert's random UUID. A flapping vital that
     re-fires with a fresh ALT-{uuid} each cycle is now correctly
     suppressed for the cooldown window.
  3. GLOBAL CIRCUIT BREAKER — a hard cap on emails/hour regardless of
     content. If something goes truly haywire, the inbox is protected.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from typing import TYPE_CHECKING

import boto3
import structlog

from src.config import settings

if TYPE_CHECKING:
    from src.models.alert import Alert

logger = structlog.get_logger()

# Per-condition cooldown: one email per (asset, metric, severity) per window.
RATE_LIMIT_SECONDS = 900  # 15 min
# Global circuit breaker: never exceed this many emails in a rolling hour.
GLOBAL_EMAIL_CAP_PER_HOUR = 6
GLOBAL_CAP_WINDOW_S = 3600
AWS_REGION = "us-east-1"

_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _condition_key(alert: Alert) -> str:
    """Stable dedup key independent of the alert's random UUID AND of the
    reading's exact value. "VIBRATION warning at 5.27 mm/s" and
    "VIBRATION warning at 4.64 mm/s" are the SAME condition — a vital
    oscillating near its threshold — and must collapse to one key
    (Task #243: the value-sensitive key turned one flapping point into
    nine digest rows, and let value jitter bypass the critical-email
    cooldown). Numbers are normalized to '#'."""
    msg = _NUM_RE.sub("#", alert.message or "")[:80]
    return f"{alert.asset_id}|{alert.severity}|{msg}"


def _value_range(group: list[Alert]) -> str:
    """Human-readable spread of readings across a collapsed group, e.g.
    ' (4.50–5.27)'. The first number in the message is the reading."""
    vals = []
    for a in group:
        m = _NUM_RE.search(a.message or "")
        if m:
            vals.append(float(m.group()))
    distinct = sorted(set(vals))
    if len(distinct) > 1:
        return f" ({distinct[0]:g}–{distinct[-1]:g})"
    return ""


class NotificationEngine:
    """Sends alert notifications via AWS SES (email) and SNS (SMS)."""

    def __init__(self) -> None:
        # Keyed on CONDITION (asset+metric+severity), not alert.id — so a
        # flapping vital with fresh UUIDs each cycle is still suppressed.
        self._last_notified: dict[str, float] = {}
        # Rolling window of email send timestamps for the global circuit breaker.
        self._email_times: deque[float] = deque()
        # WARNING-level alerts accumulate here for the digest instead of emailing.
        self._warning_digest: list[Alert] = []
        # Steady-state memory (Task #243): condition key -> last-seen ts.
        # A condition reported in a previous digest is suppressed while it
        # stays continuously active; it ages out only after being quiet
        # for warning_digest_steady_ttl. Report on ENTRY, not persistence.
        self._reported_conditions: dict[str, float] = {}
        self._ses = boto3.client("ses", region_name=AWS_REGION)
        self._sns = boto3.client("sns", region_name=AWS_REGION)
        self.log = logger.bind(component="notifier")
        self.log.info("notifier_init", backend="aws_ses_sns")

    def _is_rate_limited(self, key: str) -> bool:
        last = self._last_notified.get(key)
        if last is None:
            return False
        return (time.time() - last) < RATE_LIMIT_SECONDS

    def _global_cap_exceeded(self) -> bool:
        """Circuit breaker: drop the oldest timestamps outside the window,
        then check whether we're at the hourly cap."""
        now = time.time()
        while self._email_times and now - self._email_times[0] > GLOBAL_CAP_WINDOW_S:
            self._email_times.popleft()
        return len(self._email_times) >= GLOBAL_EMAIL_CAP_PER_HOUR

    async def notify(self, alert: Alert) -> None:
        """Route an alert. CRITICAL → immediate email (deduped + capped).
        WARNING/INFO → digest buffer (flushed periodically, never per-alert)."""
        if not settings.notifications_enabled:
            return
        if alert.status != "open":
            return

        # ── Layer 1: severity gate ──────────────────────────────────────
        # Only CRITICAL emails in real time. Everything else digests.
        if alert.severity != "critical":
            self._warning_digest.append(alert)
            self.log.debug("alert_digested", alert_id=alert.id, severity=alert.severity)
            return

        # ── Layer 2: condition-keyed dedup (not alert.id) ───────────────
        key = _condition_key(alert)
        if self._is_rate_limited(key):
            self.log.debug("notification_rate_limited", key=key, alert_id=alert.id)
            return

        # ── Layer 3: global circuit breaker ─────────────────────────────
        if self._global_cap_exceeded():
            self.log.warning(
                "notification_global_cap_hit",
                cap=GLOBAL_EMAIL_CAP_PER_HOUR,
                window_s=GLOBAL_CAP_WINDOW_S,
                alert_id=alert.id,
            )
            return

        self._last_notified[key] = time.time()
        self._email_times.append(time.time())

        tasks = []
        if settings.notification_email_to:
            tasks.append(self._send_email(alert))
        if settings.notification_sms_to:  # already critical-only here
            tasks.append(self._send_sms(alert))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def flush_warning_digest(self) -> None:
        """Send ONE digest email for NEW warning conditions, then clear the
        buffer. Called on a timer by the scheduler (e.g. hourly).

        Steady-state suppression (Task #243): conditions already reported
        in a previous digest and still active are NOT re-reported as rows —
        they appear only as a one-line "still active" summary, and if the
        whole batch is steady-state, no email is sent at all. Silence is
        golden; report on entry, not on persistence (ISA-18.2)."""
        if not settings.notifications_enabled or not settings.notification_email_to:
            self._warning_digest.clear()
            return
        if not self._warning_digest:
            return
        batch = self._warning_digest
        self._warning_digest = []

        # Group by value-insensitive condition key.
        grouped: dict[str, list[Alert]] = {}
        for a in batch:
            grouped.setdefault(_condition_key(a), []).append(a)

        # Split new vs steady-state; refresh last-seen + expire quiet entries.
        now = time.time()
        ttl = settings.warning_digest_steady_ttl
        self._reported_conditions = {k: t for k, t in self._reported_conditions.items() if now - t < ttl}
        new_groups: dict[str, list[Alert]] = {}
        ongoing_groups: dict[str, list[Alert]] = {}
        for key, group in grouped.items():
            if key in self._reported_conditions:
                ongoing_groups[key] = group
            else:
                new_groups[key] = group
            self._reported_conditions[key] = now

        if not new_groups:
            self.log.info(
                "warning_digest_all_steady_state",
                suppressed_conditions=len(ongoing_groups),
                suppressed_events=len(batch),
            )
            return

        try:
            await self._send_digest(new_groups, ongoing_groups)
            self.log.info(
                "warning_digest_sent",
                new_conditions=len(new_groups),
                steady_suppressed=len(ongoing_groups),
                events=len(batch),
            )
        except Exception as e:  # noqa: BLE001 — digest must never crash the loop
            self.log.error("warning_digest_failed", count=len(batch), error=str(e))

    async def _send_email(self, alert: Alert) -> None:
        """Send alert notification via AWS SES."""
        recipients = [e.strip() for e in settings.notification_email_to.split(",") if e.strip()]
        if not recipients:
            return

        subject = f"[Aevus {alert.severity.upper()}] {alert.asset_name}: {alert.message}"
        body_text = (
            f"Alert ID: {alert.id}\n"
            f"Severity: {alert.severity}\n"
            f"Asset: {alert.asset_name} ({alert.asset_id})\n"
            f"Message: {alert.message}\n"
            f"Detected: {alert.detected_at.isoformat()}\n"
            f"\n---\nAevus SCADA Intelligence | Intrepid Logic LLC"
        )
        body_html = (
            f"<h2 style='color:{self._severity_color(alert.severity)}'"
            f">Aevus {alert.severity.upper()} Alert</h2>"
            f"<table style='font-family:sans-serif;font-size:14px'>"
            f"<tr><td><b>Asset:</b></td><td>{alert.asset_name} ({alert.asset_id})</td></tr>"
            f"<tr><td><b>Severity:</b></td><td>{alert.severity}</td></tr>"
            f"<tr><td><b>Message:</b></td><td>{alert.message}</td></tr>"
            f"<tr><td><b>Detected:</b></td><td>{alert.detected_at.isoformat()}</td></tr>"
            f"<tr><td><b>Alert ID:</b></td><td style='font-family:monospace'>{alert.id}</td></tr>"
            f"</table>"
            f"<hr><p style='color:#888;font-size:12px'>"
            f"Aevus SCADA Intelligence | Intrepid Logic LLC</p>"
        )

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self._ses.send_email(
                    Source=settings.smtp_from,
                    Destination={"ToAddresses": recipients},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": body_text, "Charset": "UTF-8"},
                            "Html": {"Data": body_html, "Charset": "UTF-8"},
                        },
                    },
                ),
            )
            self.log.info("ses_email_sent", alert_id=alert.id, recipients=recipients)
        except Exception as e:
            self.log.error("ses_email_failed", alert_id=alert.id, error=str(e))

    async def _send_digest(
        self,
        new_groups: dict[str, list[Alert]],
        ongoing_groups: dict[str, list[Alert]],
    ) -> None:
        """Send ONE rolled-up email for the NEW warning conditions.

        Each row is one condition (value-insensitive), showing the most
        recent message, the event count, and the spread of readings.
        Steady-state conditions appear only as a one-line summary."""
        recipients = [e.strip() for e in settings.notification_email_to.split(",") if e.strip()]
        if not recipients:
            return

        n_new = len(new_groups)
        n_events = sum(len(g) for g in new_groups.values())
        subject = f"[Aevus Digest] {n_new} new warning condition(s) · {n_events} event(s)"

        rows_text = []
        rows_html = []
        for group in new_groups.values():
            sample = group[-1]  # most recent reading, not the oldest
            count = len(group)
            badge = f" ×{count}" if count > 1 else ""
            spread = _value_range(group)
            rows_text.append(f"- {sample.asset_name} ({sample.asset_id}): {sample.message}{spread}{badge}")
            rows_html.append(
                f"<tr><td style='padding:4px 10px'>{sample.asset_name} "
                f"<span style='color:#888'>({sample.asset_id})</span></td>"
                f"<td style='padding:4px 10px'>{sample.message}{spread}</td>"
                f"<td style='padding:4px 10px;font-family:monospace;text-align:right'>{count}</td></tr>"
            )

        ongoing_line = ""
        if ongoing_groups:
            n_ongoing_events = sum(len(g) for g in ongoing_groups.values())
            ongoing_line = (
                f"{len(ongoing_groups)} previously-reported condition(s) still active "
                f"({n_ongoing_events} event(s) this period) — suppressed per steady-state policy."
            )

        summary = await self._llm_summary(new_groups, ongoing_groups)

        body_text = (
            f"Aevus warning digest — {n_new} new condition(s), {n_events} event(s).\n\n"
            + (f"{summary}\n\n" if summary else "")
            + "\n".join(rows_text)
            + (f"\n\n{ongoing_line}" if ongoing_line else "")
            + "\n\n---\nThese are WARNING-level conditions, batched per ISA-18.2 to "
            "avoid alarm flooding. CRITICAL alerts are emailed individually in real time.\n"
            "Aevus SCADA Intelligence | Intrepid Logic LLC"
        )
        body_html = (
            "<h2 style='color:#F59E0B'>Aevus Warning Digest</h2>"
            f"<p style='font-family:sans-serif;font-size:13px;color:#444'>"
            f"{n_new} new warning condition(s) · {n_events} event(s) since last digest.</p>"
            + (
                f"<p style='font-family:sans-serif;font-size:13px;color:#333;"
                f"border-left:3px solid #F59E0B;padding-left:10px'>{summary}</p>"
                if summary
                else ""
            )
            + "<table style='font-family:sans-serif;font-size:13px;border-collapse:collapse'>"
            "<tr style='background:#f5f5f5'><th style='padding:4px 10px;text-align:left'>Asset</th>"
            "<th style='padding:4px 10px;text-align:left'>Condition</th>"
            "<th style='padding:4px 10px;text-align:right'>Count</th></tr>"
            + "".join(rows_html)
            + "</table>"
            + (
                f"<p style='font-family:sans-serif;font-size:12px;color:#888'>{ongoing_line}</p>"
                if ongoing_line
                else ""
            )
            + "<hr><p style='color:#888;font-size:12px'>WARNING-level conditions are "
            "batched per ISA-18.2 to prevent alarm flooding. CRITICAL alerts are sent "
            "individually in real time.<br>Aevus SCADA Intelligence | Intrepid Logic LLC</p>"
        )

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self._ses.send_email(
                Source=settings.smtp_from,
                Destination={"ToAddresses": recipients},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": body_text, "Charset": "UTF-8"},
                        "Html": {"Data": body_html, "Charset": "UTF-8"},
                    },
                },
            ),
        )

    async def _llm_summary(
        self,
        new_groups: dict[str, list[Alert]],
        ongoing_groups: dict[str, list[Alert]],
    ) -> str:
        """Optional 2-3 sentence operator summary for the digest header
        (flag-gated, settings.warning_digest_llm). Clusters related
        warnings and says what is new vs already-known. Best-effort:
        any failure returns "" and the deterministic digest stands alone.
        Read-only — the model sees alarm text, never controls anything."""
        if not settings.warning_digest_llm or not new_groups:
            return ""
        lines = []
        for group in new_groups.values():
            s = group[-1]
            lines.append(f"NEW ({len(group)}x): {s.asset_name} [{s.asset_id}] {s.message}")
        for group in ongoing_groups.values():
            s = group[-1]
            lines.append(f"ONGOING ({len(group)}x): {s.asset_name} [{s.asset_id}] {s.message}")
        prompt = (
            "You write the 2-3 sentence header of a SCADA warning-digest email "
            "for a control-room operator. Cluster related warnings, lead with "
            "what is NEW, and note shared likely causes only when the data "
            "supports it. No markdown, no preamble, plain prose only.\n\n"
            "Warning conditions this period:\n" + "\n".join(lines[:30])
        )
        try:
            if not hasattr(self, "_bedrock"):
                self._bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
            import json as _json

            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            }
            loop = asyncio.get_running_loop()
            resp = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self._bedrock.invoke_model(
                        modelId=settings.warning_digest_llm_model,
                        body=_json.dumps(body),
                        contentType="application/json",
                    ),
                ),
                timeout=15,
            )
            payload = _json.loads(resp["body"].read())
            text = "".join(b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text").strip()
            if text:
                self.log.info("digest_llm_summary_ok", chars=len(text))
            return text
        except Exception as e:  # noqa: BLE001 — summary is garnish, never load-bearing
            self.log.warning("digest_llm_summary_failed", error=str(e)[:200])
            return ""

    async def _send_sms(self, alert: Alert) -> None:
        """Send SMS via AWS SNS."""
        numbers = [n.strip() for n in settings.notification_sms_to.split(",") if n.strip()]
        if not numbers:
            return

        body = f"[Aevus {alert.severity.upper()}] {alert.asset_name}: {alert.message}"

        loop = asyncio.get_running_loop()
        for number in numbers:
            try:
                await loop.run_in_executor(
                    None,
                    lambda n=number: self._sns.publish(
                        PhoneNumber=n,
                        Message=body,
                        MessageAttributes={
                            "AWS.SNS.SMS.SenderID": {
                                "DataType": "String",
                                "StringValue": "AEVUS",
                            },
                            "AWS.SNS.SMS.SMSType": {
                                "DataType": "String",
                                "StringValue": "Transactional",
                            },
                        },
                    ),
                )
                self.log.info("sns_sms_sent", alert_id=alert.id, to=number)
            except Exception as e:
                self.log.error("sns_sms_failed", alert_id=alert.id, to=number, error=str(e))

    @staticmethod
    def _severity_color(severity: str) -> str:
        return {
            "critical": "#EF4444",
            "high": "#F59E0B",
            "warning": "#F59E0B",
            "medium": "#3B82F6",
            "low": "#6B7280",
        }.get(severity, "#6B7280")
