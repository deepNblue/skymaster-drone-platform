"""SMTP mailer — one shared service for password reset, anomaly alerts, etc.

Config via env (all optional — mailer is best-effort):
    SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD
    SMTP_TLS (default: true)
    SMTP_FROM (default: no-reply@skymaster.local)
    SMTP_FROM_NAME (default: "SkyMaster Platform")

When SMTP_HOST is not set → falls back to console print (dev mode).
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

logger = logging.getLogger(__name__)


class MailerConfig:
    def __init__(self) -> None:
        self.host: Optional[str] = os.getenv("SMTP_HOST") or None
        self.port: int = int(os.getenv("SMTP_PORT", "587"))
        self.user: Optional[str] = os.getenv("SMTP_USER") or None
        self.password: Optional[str] = os.getenv("SMTP_PASSWORD") or None
        self.tls: bool = os.getenv("SMTP_TLS", "true").lower() in (
            "1", "true", "yes", "on",
        )
        self.from_addr: str = os.getenv("SMTP_FROM", "no-reply@skymaster.local")
        self.from_name: str = os.getenv("SMTP_FROM_NAME", "SkyMaster Platform")

    @property
    def enabled(self) -> bool:
        return bool(self.host)


def _build_msg(cfg: MailerConfig, to: str, subject: str, body: str, html: Optional[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg.from_name, cfg.from_addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _send_sync(cfg: MailerConfig, msg: EmailMessage) -> None:
    with smtplib.SMTP(cfg.host, cfg.port, timeout=10) as s:  # type: ignore[arg-type]
        if cfg.tls:
            s.starttls()
        if cfg.user and cfg.password:
            s.login(cfg.user, cfg.password)
        s.send_message(msg)


async def send_email(
    to: str,
    subject: str,
    body: str,
    html: Optional[str] = None,
) -> bool:
    """Send an email. Returns True on success, False otherwise.

    In dev mode (SMTP_HOST not set) the message is printed to stdout.
    """
    cfg = MailerConfig()
    if not cfg.enabled:
        # Dev fallback — never let missing SMTP break the caller.
        print(f"[MAIL:DEV] To={to} Subject={subject}\n---\n{body}\n---", flush=True)
        return True
    msg = _build_msg(cfg, to, subject, body, html)
    try:
        await asyncio.get_running_loop().run_in_executor(None, _send_sync, cfg, msg)
        logger.info("mail sent to=%s subject=%r", to, subject)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("mail failed to=%s subject=%r err=%s", to, subject, exc)
        return False
