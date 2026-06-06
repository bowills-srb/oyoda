from __future__ import annotations

import os
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, Dict, List, Mapping, Optional
from uuid import UUID

import httpx

from app.services.integrations.gmail_inbox_poller import (
    GMAIL_API_BASE,
    GmailEmailParser,
    GmailInboxPoller,
    GmailReplySender,
    GmailTokenManager,
)
from app.services.transport.base import (
    Attachment,
    ChannelTransport,
    MessageDirection,
    NormalizedMessage,
    NormalizedParty,
    TransportCapability,
)
from app.services.transport.credentials import OperatorCredentialRecord


class GmailTransport(ChannelTransport):
    """Thin additive adapter over the existing Gmail poller/reply sender."""

    def __init__(
        self,
        *,
        operator_id: str,
        tenant_id: str,
        watched_address: str,
        token_manager: GmailTokenManager,
        provider_alias: str = "gmail",
        poll_label: str = "INBOX",
        processed_label: str = "Oyvoda-Processed",
    ):
        self.operator_id = operator_id
        self.tenant_id = tenant_id
        self.watched_address = watched_address
        self.token_manager = token_manager
        self.provider_alias = provider_alias
        self.poll_label = poll_label
        self.processed_label = processed_label
        self._parser = GmailEmailParser()
        self._poller = GmailInboxPoller(
            operator_id=operator_id,
            company_id=UUID(tenant_id),
            token_manager=token_manager,
            watched_email=watched_address,
            poll_label=poll_label,
            processed_label=processed_label,
            db=None,
        )
        self._reply_sender = GmailReplySender(token_manager)

    @property
    def channel(self) -> str:
        return "gmail"

    @property
    def capabilities(self) -> frozenset[TransportCapability]:
        return frozenset(
            {
                TransportCapability.POLL_INBOX,
                TransportCapability.SEND_REPLY,
                TransportCapability.FETCH_THREAD_HISTORY,
                TransportCapability.MARK_READ,
                TransportCapability.GET_MESSAGE,
            }
        )

    @classmethod
    def from_credential_record(cls, record: OperatorCredentialRecord) -> "GmailTransport":
        client_id = os.getenv("GMAIL_CLIENT_ID", "")
        client_secret = os.getenv("GMAIL_CLIENT_SECRET", "")
        refresh_token = str(record.credential_blob.get("refresh_token") or "")
        if not client_id or not client_secret:
            raise RuntimeError("gmail_transport_not_configured: missing GMAIL_CLIENT_ID/GMAIL_CLIENT_SECRET")
        if not refresh_token:
            raise RuntimeError("gmail_transport_not_configured: missing operator refresh token")
        if not record.tenant_id:
            raise RuntimeError("gmail_transport_not_configured: missing tenant_id")

        token_manager = GmailTokenManager(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
        )
        return cls(
            operator_id=record.operator_id,
            tenant_id=record.tenant_id,
            watched_address=record.watched_address,
            token_manager=token_manager,
            provider_alias=str(record.metadata.get("provider_alias") or "gmail"),
        )

    async def poll_inbox(
        self,
        *,
        query_mode: str = "unread",
        limit: Optional[int] = None,
    ) -> list[NormalizedMessage]:
        token = await self.token_manager.get_access_token()
        headers = self.token_manager.auth_header(token)
        observed_at = datetime.now(timezone.utc)
        message_ids = await self._poller._list_message_ids(headers, query_mode=query_mode)
        if limit is not None:
            message_ids = message_ids[:limit]

        messages: list[NormalizedMessage] = []
        for message_id in message_ids:
            raw = await self._poller._get_full_message(message_id, headers)
            if not raw:
                continue
            messages.append(self._normalize_gmail_message(raw, observed_at=observed_at))
        return messages

    async def get_message(self, message_ref: str) -> Optional[NormalizedMessage]:
        token = await self.token_manager.get_access_token()
        headers = self.token_manager.auth_header(token)
        raw = await self._poller._get_full_message(message_ref, headers)
        if not raw:
            return None
        return self._normalize_gmail_message(raw)

    async def fetch_thread_history(self, thread_ref: str) -> list[NormalizedMessage]:
        token = await self.token_manager.get_access_token()
        headers = self.token_manager.auth_header(token)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GMAIL_API_BASE}/users/me/threads/{thread_ref}",
                headers=headers,
                params={"format": "full"},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            thread_data = resp.json()

        messages = [
            self._normalize_gmail_message(raw_message)
            for raw_message in thread_data.get("messages", []) or []
        ]
        messages.sort(
            key=lambda m: (
                m.sent_at or datetime.min.replace(tzinfo=timezone.utc),
                m.message_ref,
            )
        )
        return messages

    async def send_reply(
        self,
        *,
        thread_ref: str,
        in_reply_to_ref: Optional[str],
        to_party: NormalizedParty,
        subject: str,
        body_text: str,
        operator_name: str,
        from_email: Optional[str] = None,
    ) -> bool:
        return await self._reply_sender.reply(
            thread_id=thread_ref,
            in_reply_to=in_reply_to_ref or "",
            to_address=to_party.email or "",
            to_name=to_party.display_name or (to_party.email or "Guest"),
            subject=subject,
            body=body_text,
            operator_name=operator_name,
            from_email=from_email,
        )

    async def mark_read(self, message_ref: str) -> None:
        token = await self.token_manager.get_access_token()
        headers = self.token_manager.auth_header(token)
        await self._poller._mark_read(message_ref, headers)

    def _normalize_gmail_message(
        self,
        raw_message: Mapping[str, Any],
        *,
        observed_at: Optional[datetime] = None,
    ) -> NormalizedMessage:
        payload = raw_message.get("payload", {}) or {}
        headers = self._header_map(payload)

        subject = headers.get("subject") or None
        thread_subject = self._canonical_thread_subject(subject)
        from_raw = headers.get("from", "")
        to_raw = headers.get("to", "")
        from_name, from_email = parseaddr(from_raw)
        to_name, to_email = parseaddr(to_raw)

        raw_body = self._parser._decode_gmail_payload(payload)
        body_text = self._parser.extract_plain_text_body(raw_body) if raw_body else ""
        attachments = tuple(self._extract_attachments(payload))

        sent_at = self._parse_sent_at(headers.get("date", ""), raw_message.get("internalDate"))
        direction = self._infer_direction(from_email=from_email)

        return NormalizedMessage(
            channel=self.channel,
            message_ref=str(raw_message.get("id") or ""),
            thread_ref=str(raw_message.get("threadId") or ""),
            direction=direction,
            sender=NormalizedParty(
                email=from_email or None,
                display_name=from_name or "",
            ),
            recipient=NormalizedParty(
                email=to_email or None,
                display_name=to_name or "",
            ),
            subject=subject,
            thread_subject=thread_subject,
            body_text=body_text or "",
            body_html=raw_body or None,
            sent_at=sent_at,
            received_at=observed_at,
            in_reply_to_ref=None,
            provider_message_type="email",
            attachments=attachments,
            raw_provider_payload=raw_message,
        )

    def _infer_direction(self, *, from_email: str) -> MessageDirection:
        if (from_email or "").strip().lower() == (self.watched_address or "").strip().lower():
            return MessageDirection.OUTBOUND
        return MessageDirection.INBOUND

    def _header_map(self, payload: Mapping[str, Any]) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        for header in payload.get("headers", []) or []:
            name = str(header.get("name") or "").strip().lower()
            if not name:
                continue
            headers[name] = str(header.get("value") or "")
        return headers

    def _canonical_thread_subject(self, subject: Optional[str]) -> Optional[str]:
        value = (subject or "").strip()
        if not value:
            return None
        # Strip repeated email reply/forward prefixes to approximate a
        # canonical thread subject while preserving the human-readable stem.
        while True:
            lowered = value.lower()
            if lowered.startswith("re:"):
                value = value[3:].strip()
                continue
            if lowered.startswith("fwd:"):
                value = value[4:].strip()
                continue
            if lowered.startswith("fw:"):
                value = value[3:].strip()
                continue
            break
        return value or subject

    def _parse_sent_at(
        self,
        date_header: str,
        internal_date_millis: Any,
    ) -> Optional[datetime]:
        if date_header:
            try:
                parsed = parsedate_to_datetime(date_header)
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed
            except Exception:
                pass
        if internal_date_millis:
            try:
                return datetime.fromtimestamp(
                    int(str(internal_date_millis)) / 1000.0,
                    tz=timezone.utc,
                )
            except Exception:
                pass
        return None

    def _extract_attachments(self, payload: Mapping[str, Any]) -> List[Attachment]:
        attachments: List[Attachment] = []

        def walk(part: Mapping[str, Any]) -> None:
            filename = str(part.get("filename") or "")
            body = part.get("body", {}) or {}
            attachment_ref = body.get("attachmentId")
            headers = {
                str(h.get("name") or "").strip().lower(): str(h.get("value") or "")
                for h in (part.get("headers", []) or [])
            }
            if filename or attachment_ref:
                attachments.append(
                    Attachment(
                        filename=filename,
                        mime_type=str(part.get("mimeType") or ""),
                        size_bytes=int(body.get("size")) if body.get("size") is not None else None,
                        provider_attachment_ref=str(attachment_ref) if attachment_ref else None,
                        inline=bool(headers.get("content-id")),
                        content_id=headers.get("content-id") or None,
                    )
                )
            for child in part.get("parts", []) or []:
                walk(child)

        walk(payload)
        return attachments
