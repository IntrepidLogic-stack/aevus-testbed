"""
Aevus — Notification Engine
Sends alerts via email (SMTP) and SMS (Twilio-compatible webhook).
Rate-limited: max 1 notification per alert per 15 minutes.
"""
from __future__ import annotations

import asyncio
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from src.config import settings
from src.models.alert import Alert

logger = structlog.get_logger()

# Rate limit: 15 minutes per alert ID
RATE_LIMIT_SECONDS = 900


class NotificationEngine:
    """Sends alert notifications via email and SMS."""

    def __init__(self) -> None:
        self._last_notified: dict[str, float] = {}
        self.log = logger.bind(component="notifier")

    def _is_rate_limited(self, alert_id: str) -> bool:
        """Check if we recently notified for this alert."""
        last = self._last_notified.get(alert_id)
        if last is None:
            return False
        return (time.time() - last) < RATE_LIMIT_SECONDS

    async def notify(self, alert: Alert) -> None:
        """Send notifications for a new alert.

        Only notifies on NEW alerts (status=open).
        Respects rate limiting and notifications_enabled flag.
        """
        if not settings.notifications_enabled:
            return

        if alert.status != "open":
            return

        if self._is_rate_limited(alert.id):
            self.log.debug("notification_rate_limited", alert_id=alert.id)
            return

        self._last_notified[alert.id] = time.time()

        # Route by severity
        tasks = []
        if settings.notification_email_to:
            tasks.append(self._send_email(alert))
        if alert.severity == "critical" and settings.notification_sms_to:
            tasks.append(self._send_sms(alert))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _send_email(self, alert: Alert) -> None:
        """Send alert notification via SMTP."""
        recipients = [e.strip() for e in settings.notification_email_to.split(",") if e.strip()]
        if not recipients:
            return

        subject = f"[Aevus {alert.severity.upper()}] {alert.asset_name}: {alert.message}"
        body = (
            f"Alert ID: {alert.id}\n"
            f"Severity: {alert.severity}\n"
            f"Asset: {alert.asset_name} ({alert.asset_id})\n"
            f"Message: {alert.message}\n"
            f"Detected: {alert.detected_at.isoformat()}\n"
        )

        msg = MIMEMultipart()
        msg["From"] = settings.smtp_from
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._smtp_send, msg, recipients)
            self.log.info("email_sent", alert_id=alert.id, recipients=recipients)
        except Exception as e:
            self.log.error("email_send_failed", alert_id=alert.id, error=str(e))

    def _smtp_send(self, msg: MIMEMultipart, recipients: list[str]) -> None:
        """Blocking SMTP send (run in executor)."""
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            if settings.smtp_user and settings.smtp_password:
                server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_from, recipients, msg.as_string())

    async def _send_sms(self, alert: Alert) -> None:
        """Send SMS via Twilio-compatible HTTP webhook."""
        numbers = [n.strip() for n in settings.notification_sms_to.split(",") if n.strip()]
        if not numbers or not settings.twilio_account_sid:
            return

        try:
            import urllib.request
            import urllib.parse
            import base64

            url = (
                f"https://api.twilio.com/2010-04-01/Accounts/"
                f"{settings.twilio_account_sid}/Messages.json"
            )
            auth = base64.b64encode(
                f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()
            ).decode()

            body_text = f"[Aevus {alert.severity.upper()}] {alert.asset_name}: {alert.message}"

            loop = asyncio.get_running_loop()
            for number in numbers:
                data = urllib.parse.urlencode({
                    "To": number,
                    "From": settings.twilio_from_number,
                    "Body": body_text,
                }).encode()
                req = urllib.request.Request(url, data=data)
                req.add_header("Authorization", f"Basic {auth}")
                await loop.run_in_executor(None, urllib.request.urlopen, req)
                self.log.info("sms_sent", alert_id=alert.id, to=number)
        except Exception as e:
            self.log.error("sms_send_failed", alert_id=alert.id, error=str(e))
