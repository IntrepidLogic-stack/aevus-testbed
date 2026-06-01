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


def _condition_key(alert: Alert) -> str:
    """Stable dedup key independent of the alert's random UUID. Two fires
    for the same asset+metric+severity collapse to one notification."""
    # Derive a metric-ish token from the message (the message embeds the
    # metric label); fall back to asset+severity if absent.
    return f"{alert.asset_id}|{alert.severity}|{(alert.message or '')[:60]}"


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
        """Send ONE digest email summarizing buffered WARNING/INFO alerts,
        then clear the buffer. Called on a timer by the scheduler (e.g.
        hourly). No-op when the buffer is empty — silence is golden."""
        if not settings.notifications_enabled or not settings.notification_email_to:
            self._warning_digest.clear()
            return
        if not self._warning_digest:
            return
        batch = self._warning_digest
        self._warning_digest = []
        try:
            await self._send_digest(batch)
            self.log.info("warning_digest_sent", count=len(batch))
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

    async def _send_digest(self, alerts: list[Alert]) -> None:
        """Send ONE rolled-up email for a batch of WARNING/INFO alerts.
        Deduplicates by (asset, message) so a flapping vital shows as a
        single row with a count, not N rows."""
        recipients = [e.strip() for e in settings.notification_email_to.split(",") if e.strip()]
        if not recipients:
            return

        # Collapse duplicates: key → (sample_alert, count)
        grouped: dict[str, list[Alert]] = {}
        for a in alerts:
            grouped.setdefault(_condition_key(a), []).append(a)

        n_unique = len(grouped)
        n_total = len(alerts)
        subject = f"[Aevus Digest] {n_unique} warning condition(s) · {n_total} event(s)"

        rows_text = []
        rows_html = []
        for group in grouped.values():
            sample = group[0]
            count = len(group)
            badge = f" ×{count}" if count > 1 else ""
            rows_text.append(f"- {sample.asset_name} ({sample.asset_id}): {sample.message}{badge}")
            rows_html.append(
                f"<tr><td style='padding:4px 10px'>{sample.asset_name} "
                f"<span style='color:#888'>({sample.asset_id})</span></td>"
                f"<td style='padding:4px 10px'>{sample.message}</td>"
                f"<td style='padding:4px 10px;font-family:monospace;text-align:right'>{count}</td></tr>"
            )

        body_text = (
            f"Aevus warning digest — {n_unique} condition(s), {n_total} event(s).\n\n"
            + "\n".join(rows_text)
            + "\n\n---\nThese are WARNING-level conditions, batched per ISA-18.2 to "
            "avoid alarm flooding. CRITICAL alerts are emailed individually in real time.\n"
            "Aevus SCADA Intelligence | Intrepid Logic LLC"
        )
        body_html = (
            "<h2 style='color:#F59E0B'>Aevus Warning Digest</h2>"
            f"<p style='font-family:sans-serif;font-size:13px;color:#444'>"
            f"{n_unique} warning condition(s) · {n_total} event(s) since last digest.</p>"
            "<table style='font-family:sans-serif;font-size:13px;border-collapse:collapse'>"
            "<tr style='background:#f5f5f5'><th style='padding:4px 10px;text-align:left'>Asset</th>"
            "<th style='padding:4px 10px;text-align:left'>Condition</th>"
            "<th style='padding:4px 10px;text-align:right'>Count</th></tr>" + "".join(rows_html) + "</table>"
            "<hr><p style='color:#888;font-size:12px'>WARNING-level conditions are "
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
