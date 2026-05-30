"""
Aevus — Notification Engine
Sends alerts via AWS SES (email) and AWS SNS (SMS).
Rate-limited: max 1 notification per alert per 15 minutes.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import boto3
import structlog

from src.config import settings

if TYPE_CHECKING:
    from src.models.alert import Alert

logger = structlog.get_logger()

RATE_LIMIT_SECONDS = 900
AWS_REGION = "us-east-1"


class NotificationEngine:
    """Sends alert notifications via AWS SES (email) and SNS (SMS)."""

    def __init__(self) -> None:
        self._last_notified: dict[str, float] = {}
        self._ses = boto3.client("ses", region_name=AWS_REGION)
        self._sns = boto3.client("sns", region_name=AWS_REGION)
        self.log = logger.bind(component="notifier")
        self.log.info("notifier_init", backend="aws_ses_sns")

    def _is_rate_limited(self, alert_id: str) -> bool:
        last = self._last_notified.get(alert_id)
        if last is None:
            return False
        return (time.time() - last) < RATE_LIMIT_SECONDS

    async def notify(self, alert: Alert) -> None:
        """Send notifications for a new alert."""
        if not settings.notifications_enabled:
            return

        if alert.status != "open":
            return

        if self._is_rate_limited(alert.id):
            self.log.debug("notification_rate_limited", alert_id=alert.id)
            return

        self._last_notified[alert.id] = time.time()

        tasks = []
        if settings.notification_email_to:
            tasks.append(self._send_email(alert))
        if alert.severity == "critical" and settings.notification_sms_to:
            tasks.append(self._send_sms(alert))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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
