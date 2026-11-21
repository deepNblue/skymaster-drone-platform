"""Email poller for AAS — periodically check inbox for status replies and parse them.

v2.3 E7.1 — run as background task, calls parse-receipt API to update status.
Uses IMAP to connect to inbox, search for unread messages matching approval.
"""
import asyncio
import email
from datetime import datetime, timedelta
from email.header import decode_header
from typing import Optional
import imaplib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.approval_city_templates import CityApprovalTemplate, ApprovalStatusReceipt
from app.models.flight_approval import FlightApproval
from app.deps import get_db
from app.services.email_config import get_system_email_config


class EmailPoller:
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def poll_once(self, db: AsyncSession) -> int:
        """Check inbox once, return number of processed messages."""
        config = get_system_email_config()
        processed = 0

        try:
            mail = imaplib.IMAP4_SSL(config.imap_host, config.imap_port)
            mail.login(config.imap_user, config.imap_password)

            # Select inbox
            mail.select("inbox")

            # Search for unread messages received in last 30 days
            since_date = (datetime.utcnow() - timedelta(days=30)).strftime("%d-%b-%Y")
            status, messages = mail.search(None, f"(UNREAD SINCE {since_date})")

            if status != "OK":
                return 0

            for msg_id in messages[0].split():
                status, data = mail.fetch(msg_id, "(RFC822)")
                if status != "OK":
                    continue
                processed += await self._process_message(data[0][1], db)
                # Mark as read
                mail.store(msg_id, "+FLAGS", "\\Seen")

            mail.logout()
        except Exception as e:
            print(f"[EmailPoller] Error polling: {e}")

        return processed

    async def _process_message(self, raw: bytes, db: AsyncSession) -> bool:
        """Process one raw email message, try to match to an approval and parse."""
        msg = email.message_from_bytes(raw)

        # Decode subject
        subject_raw = msg["Subject"]
        if subject_raw is None:
            return False
        subject, encoding = decode_header(subject_raw)[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding or "utf-8", errors="replace")

        # Get body
        body = self._get_body(msg)

        # Try to find approval by matching subject keywords or reference
        # Heuristic: look for approval number, city, our domain in references
        # For better matching: store message-id in approval metadata when we send
        # For MVP: just try to parse and let the user manually match if ambiguous
        from app.api.v1.approval_city import match_status

        # Check all approvals in in_review status (naive, OK for MVP)
        pending = (
            await db.execute(
                select(FlightApproval).where(FlightApproval.status == "in_review")
            )
        ).scalars().all()

        matched_any = False
        for approval in pending:
            if not approval.city:
                continue
            # Find template for this city
            template = (
                await db.execute(
                    select(CityApprovalTemplate).where(
                        CityApprovalTemplate.city == approval.city,
                        CityApprovalTemplate.enabled == True,
                    )
                )
            ).scalar_one_or_none()

            if not template:
                continue

            combined = f"{subject} {body or ''}".lower()
            parsed_status = match_status(
                combined,
                template.approve_patterns,
                template.reject_patterns,
            )
            if parsed_status is None:
                continue

            # Save receipt
            receipt = ApprovalStatusReceipt(
                approval_id=approval.id,
                city_template_id=template.id,
                source="email",
                parsed_status=parsed_status or "received",
                raw_subject=subject,
                raw_body=body[:2000],  # truncate long bodies
                parsed_from_message_id=msg["Message-ID"],
            )
            db.add(receipt)

            # Update approval status if we got a definitive result
            if parsed_status in ("approved", "rejected"):
                approval.status = parsed_status

            matched_any = True
            break

        await db.commit()
        return matched_any

    def _get_body(self, msg: email.message.Message) -> Optional[str]:
        """Extract plain text body from email message."""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        return part.get_payload(decode=True).decode("utf-8", errors="replace")
                    except:
                        continue
            return None
        else:
            try:
                return msg.get_payload(decode=True).decode("utf-8", errors="replace")
            except:
                return None

    async def run_polling_loop(
        self,
        interval_minutes: float = 60.0,
    ) -> None:
        """Background polling loop."""
        self._running = True
        while self._running:
            try:
                async for db in get_db():
                    processed = await self.poll_once(db)
                    if processed > 0:
                        print(f"[EmailPoller] Processed {processed} new messages")
            except Exception as e:
                print(f"[EmailPoller] Error in polling loop: {e}")
            await asyncio.sleep(interval_minutes * 60)

    def start(self, interval_minutes: float = 60.0) -> None:
        """Start background polling."""
        if self._running:
            return
        self._task = asyncio.create_task(self.run_polling_loop(interval_minutes))

    def stop(self) -> None:
        """Stop polling."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None


# Global singleton
poller = EmailPoller()
