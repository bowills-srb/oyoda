from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Dict, Optional

import httpx

from app.services.integrations.email_inbound import ParsedEmailMessage
from app.services.integrations.email_parser_router import parse_structured_inbound_email
from app.services.integrations.email_reply import EmailReplySenderBase
from app.services.integrations.gmail_inbox_poller import (
    EmailInboxPollerBase,
    GmailEmailParser,
)
from app.services.integrations.llm_email_extractor import (
    ExtractedEmailFields,
    LLMEmailExtractor,
)

logger = logging.getLogger(__name__)

MS_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class MicrosoftTokenManager:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._access_token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None

    async def get_access_token(self) -> str:
        if self._access_token and self._token_expires_at:
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            if now < self._token_expires_at:
                return self._access_token
        return await self._refresh()

    async def _refresh(self) -> str:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                MS_TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "https://graph.microsoft.com/Mail.ReadWrite offline_access",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        self._access_token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = (
            datetime.now(timezone.utc).replace(tzinfo=None)
            + timedelta(seconds=max(60, expires_in - 300))
        )
        return self._access_token

    def auth_header(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


class MicrosoftInboxPoller(EmailInboxPollerBase):
    def __init__(
        self,
        operator_id: str,
        company_id,
        token_manager: MicrosoftTokenManager,
        watched_email: str,
        poll_label: str = "Inbox",
        processed_label: str = "Oyvoda-Processed",
        db=None,
    ):
        super().__init__(
            operator_id=operator_id,
            company_id=company_id,
            token_manager=token_manager,
            watched_email=watched_email,
            poll_label=poll_label,
            processed_label=processed_label,
            db=db,
        )
        self._parser = GmailEmailParser()

    @property
    def provider(self) -> str:
        return "microsoft"

    async def _list_message_ids(self, headers: Dict, query_mode: str = "unread"):
        select_fields = ",".join([
            "id",
            "isRead",
            "receivedDateTime",
        ])
        if query_mode == "recent_inbox":
            params = {
                "$top": "25",
                "$select": select_fields,
                "$orderby": "receivedDateTime desc",
            }
        else:
            params = {
                "$top": "50",
                "$select": select_fields,
                "$filter": "isRead eq false",
                "$orderby": "receivedDateTime desc",
            }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{MS_GRAPH_BASE}/me/mailFolders/inbox/messages",
                headers={
                    **headers,
                    "Prefer": 'outlook.body-content-type="html"',
                },
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        return [m["id"] for m in data.get("value", []) if m.get("id")]

    async def _get_full_message(self, msg_id: str, headers: Dict) -> Optional[Dict[str, Any]]:
        select_fields = ",".join([
            "id",
            "conversationId",
            "internetMessageId",
            "subject",
            "from",
            "sender",
            "toRecipients",
            "replyTo",
            "receivedDateTime",
            "body",
            "bodyPreview",
            "isRead",
        ])
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{MS_GRAPH_BASE}/me/messages/{msg_id}",
                headers={
                    **headers,
                    "Prefer": 'outlook.body-content-type="html"',
                },
                params={"$select": select_fields},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

    async def _ensure_processed_label(self, headers: Dict) -> None:
        return None

    async def _mark_read(self, msg_id: str, headers: Dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.patch(
                    f"{MS_GRAPH_BASE}/me/messages/{msg_id}",
                    headers=headers,
                    json={"isRead": True},
                )
        except Exception as e:
            logger.debug("[MicrosoftPoller] mark_read failed: %s", e)

    async def _apply_label(self, msg_id: str, headers: Dict) -> None:
        return None

    async def _parse_with_ota_fallback(
        self,
        graph_message: Dict[str, Any],
        *,
        llm_extractor_factory=None,
    ) -> Optional[ParsedEmailMessage]:
        self._last_non_guest_reason = ""
        subject = graph_message.get("subject", "") or ""
        html_body = ((graph_message.get("body") or {}).get("content") or "").strip()
        plain_body = self._parser.extract_plain_text_body(html_body) if html_body else (graph_message.get("bodyPreview") or "")

        from_obj = ((graph_message.get("from") or {}).get("emailAddress") or {})
        from_name = from_obj.get("name", "") or ""
        from_email = (from_obj.get("address", "") or "").lower()
        headers = {
            "From": f"{from_name} <{from_email}>".strip(),
            "Subject": subject,
            "Date": graph_message.get("receivedDateTime", "") or "",
            "Message-ID": graph_message.get("internetMessageId", "") or "",
        }

        return await parse_structured_inbound_email(
            source_message_id=graph_message.get("id", ""),
            subject=subject,
            plain_text=plain_body,
            raw_html=html_body,
            headers=headers,
            parser=self._parser,
            adapt_llm_inquiry=lambda extracted: self._adapt_llm_graph_inquiry(
                graph_message,
                extracted,
                subject=subject,
                plain_body=plain_body,
                html_body=html_body,
                headers=headers,
                from_name=from_name,
                from_email=from_email,
            ),
            adapt_reservation_event=lambda parsed_event: self._adapt_reservation_graph_event(graph_message, parsed_event),
            adapt_ota_inquiry=lambda parsed_ota: self._adapt_ota_graph_inquiry(graph_message, parsed_ota),
            adapt_direct_inquiry=lambda parsed_direct: self._adapt_direct_graph_inquiry(graph_message, parsed_direct),
            adapt_vendor_email=lambda parsed_vendor: self._adapt_vendor_graph_email(graph_message, parsed_vendor),
            fallback_parse=lambda: self._fallback_graph_parse(
                graph_message=graph_message,
                subject=subject,
                plain_body=plain_body,
                html_body=html_body,
                headers=headers,
                from_name=from_name,
                from_email=from_email,
            ),
            record_non_guest_drop=lambda reason: setattr(self, "_last_non_guest_reason", reason),
            llm_extractor_factory=(
                llm_extractor_factory
                or (lambda: LLMEmailExtractor(tenant_id=self.company_id))
            ),
            tenant_id=self.company_id,
            db=self.db,
        )

    def _adapt_llm_graph_inquiry(
        self,
        graph_message: Dict[str, Any],
        extracted: ExtractedEmailFields,
        *,
        subject: str,
        plain_body: str,
        html_body: str,
        headers: Dict[str, str],
        from_name: str,
        from_email: str,
    ) -> ParsedEmailMessage:
        received_at_raw = graph_message.get("receivedDateTime", "")
        try:
            received_at = datetime.fromisoformat(received_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        platform = self._parser.detect_platform(extracted.sender_email or from_email)
        property_identity_hint = extracted.external_id_hint or extracted.raw_property_mention
        return ParsedEmailMessage(
            source_provider="microsoft",
            source_message_id=graph_message["id"],
            source_thread_id=graph_message.get("conversationId", "") or "",
            gmail_message_id=graph_message["id"],
            gmail_thread_id=graph_message.get("conversationId", "") or "",
            message_id_header=graph_message.get("internetMessageId", "") or "",
            guest_name=extracted.sender_name or from_name or "Guest",
            guest_email=extracted.sender_email or from_email,
            sender_role="guest",
            reply_channel_address=extracted.sender_email or from_email,
            subject=subject,
            body=extracted.latest_guest_message,
            latest_guest_message=extracted.latest_guest_message,
            latest_operator_message="",
            conversation_context="",
            full_body=plain_body or extracted.latest_guest_message,
            extracted_links=self._parser.extract_links(html_body or plain_body or ""),
            asks=[],
            platform=platform,
            is_inquiry=True,
            lifecycle_stage="pre_booking",
            parser_source=extracted.parser_source,
            property_name=property_identity_hint,
            raw_property_mention=property_identity_hint,
            property_code="",
            platform_listing_id=extracted.platform_listing_id,
            platform_unit_id=extracted.platform_unit_id,
            source_property_id=extracted.source_property_id,
            source_account_id=extracted.provider_account_id,
            provider_property_id=extracted.provider_property_id,
            provider_account_id=extracted.provider_account_id,
            requested_check_in=extracted.requested_check_in,
            requested_check_out=extracted.requested_check_out,
            requested_guests=extracted.requested_guests,
            received_at=received_at,
            raw_from=headers.get("From", ""),
        )

    def _fallback_graph_parse(
        self,
        *,
        graph_message: Dict[str, Any],
        subject: str,
        plain_body: str,
        html_body: str,
        headers: Dict[str, str],
        from_name: str,
        from_email: str,
    ) -> Optional[ParsedEmailMessage]:
        if len((plain_body or "").strip()) < 10:
            return None

        platform = self._parser.detect_platform(from_email)
        guest_name = self._parser.extract_guest_name(
            subject,
            plain_body,
            platform,
            display_name=from_name,
            from_email=from_email,
        )
        property_name = self._parser.extract_property_name(subject, plain_body)
        check_in, check_out = self._parser.extract_dates(plain_body)
        guests = self._parser.extract_guest_count(plain_body)
        is_inquiry = self._parser.is_inquiry_subject(subject)
        latest_guest_message, conversation_context = self._parser.dissect_thread_content(plain_body)
        effective_body = latest_guest_message or plain_body
        extracted_links = self._parser.extract_links(html_body or plain_body or "")

        received_at_raw = graph_message.get("receivedDateTime", "")
        try:
            received_at = datetime.fromisoformat(received_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        return ParsedEmailMessage(
            source_provider="microsoft",
            source_message_id=graph_message["id"],
            source_thread_id=graph_message.get("conversationId", "") or "",
            gmail_message_id=graph_message["id"],
            gmail_thread_id=graph_message.get("conversationId", "") or "",
            message_id_header=graph_message.get("internetMessageId", "") or "",
            guest_name=guest_name,
            guest_email=from_email,
            subject=subject,
            body=effective_body,
            latest_guest_message=latest_guest_message or effective_body,
            conversation_context=conversation_context,
            full_body=plain_body,
            extracted_links=extracted_links,
            asks=[],
            platform=platform,
            is_inquiry=is_inquiry,
            parser_source="generic_microsoft_parser",
            property_name=property_name,
            property_code="",
            platform_listing_id="",
            platform_unit_id="",
            requested_check_in=check_in,
            requested_check_out=check_out,
            requested_guests=guests,
            received_at=received_at,
            raw_from=headers["From"],
        )

    def _adapt_ota_graph_inquiry(self, graph_message: Dict[str, Any], parsed_ota) -> Optional[ParsedEmailMessage]:
        subject = graph_message.get("subject", "") or ""
        from_obj = ((graph_message.get("from") or {}).get("emailAddress") or {})
        from_name = from_obj.get("name", "") or ""
        from_email = (from_obj.get("address", "") or "").lower()
        generic_property_name = self._parser.extract_property_name(subject, parsed_ota.message_body or "")
        body = parsed_ota.message_body or ""
        if len(body.strip()) < 10:
            return None
        latest_guest_message, conversation_context = self._parser.dissect_thread_content(body)
        effective_body = latest_guest_message or body
        extracted_links = self._parser.extract_links(((graph_message.get("body") or {}).get("content") or "") or body)

        received_at_raw = graph_message.get("receivedDateTime", "")
        try:
            received_at = datetime.fromisoformat(received_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        requested_guests = None
        if parsed_ota.guests_adults is not None or parsed_ota.guests_children is not None:
            requested_guests = (parsed_ota.guests_adults or 0) + (parsed_ota.guests_children or 0)

        return ParsedEmailMessage(
            source_provider="microsoft",
            source_message_id=graph_message["id"],
            source_thread_id=graph_message.get("conversationId", "") or "",
            gmail_message_id=graph_message["id"],
            gmail_thread_id=graph_message.get("conversationId", "") or "",
            message_id_header=graph_message.get("internetMessageId", "") or "",
            guest_name=parsed_ota.guest_name or from_name or "Guest",
            guest_email=parsed_ota.guest_email or from_email or parseaddr(from_email)[1].lower(),
            subject=subject,
            body=effective_body,
            latest_guest_message=latest_guest_message or effective_body,
            conversation_context=conversation_context,
            full_body=body,
            extracted_links=extracted_links,
            asks=list(parsed_ota.asks or []),
            platform=parsed_ota.platform,
            is_inquiry=True,
            parser_source=parsed_ota.parser_source or "ota_parser_microsoft",
            property_name=parsed_ota.property_name_hint or generic_property_name or "",
            property_code="",
            platform_listing_id=parsed_ota.platform_listing_id or "",
            platform_unit_id=parsed_ota.platform_unit_id or "",
            requested_check_in=parsed_ota.check_in,
            requested_check_out=parsed_ota.check_out,
            requested_guests=requested_guests,
            received_at=received_at,
            raw_from=f"{from_name} <{from_email}>".strip(),
        )

    def _adapt_reservation_graph_event(self, graph_message: Dict[str, Any], parsed_event) -> Optional[ParsedEmailMessage]:
        subject = graph_message.get("subject", "") or ""
        from_obj = ((graph_message.get("from") or {}).get("emailAddress") or {})
        from_name = from_obj.get("name", "") or ""
        from_email = (from_obj.get("address", "") or "").lower()
        extracted_links = self._parser.extract_links(((graph_message.get("body") or {}).get("content") or "") or "")

        received_at_raw = graph_message.get("receivedDateTime", "")
        try:
            received_at = datetime.fromisoformat(received_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        requested_guests = None
        if parsed_event.guests_adults is not None or parsed_event.guests_children is not None:
            requested_guests = (parsed_event.guests_adults or 0) + (parsed_event.guests_children or 0)

        return ParsedEmailMessage(
            source_provider="microsoft",
            source_message_id=graph_message["id"],
            source_thread_id=graph_message.get("conversationId", "") or "",
            gmail_message_id=graph_message["id"],
            gmail_thread_id=graph_message.get("conversationId", "") or "",
            message_id_header=graph_message.get("internetMessageId", "") or "",
            guest_name=parsed_event.guest_name or "Guest",
            guest_email=parsed_event.guest_email or "",
            sender_role="system",
            reply_channel_address=parsed_event.reply_channel_address or "",
            system_generated=True,
            system_event_type=parsed_event.system_event_type or "",
            subject=subject,
            body=parsed_event.summary_text or subject,
            latest_guest_message="",
            latest_operator_message="",
            conversation_context="",
            full_body=((graph_message.get("body") or {}).get("content") or parsed_event.summary_text or subject),
            extracted_links=extracted_links,
            asks=[],
            platform=parsed_event.platform,
            is_inquiry=False,
            lifecycle_stage=parsed_event.lifecycle_stage or "pre_arrival",
            parser_source=parsed_event.parser_source,
            property_name=parsed_event.property_name_hint or "",
            property_code="",
            platform_listing_id=parsed_event.platform_listing_id or "",
            platform_unit_id="",
            source_interaction_id=parsed_event.source_interaction_id or "",
            source_property_id="",
            reservation_id=parsed_event.reservation_id or "",
            requested_check_in=parsed_event.check_in,
            requested_check_out=parsed_event.check_out,
            requested_guests=requested_guests,
            received_at=received_at,
            raw_from=f"{from_name} <{from_email}>".strip(),
        )

    def _adapt_vendor_graph_email(self, graph_message: Dict[str, Any], parsed_vendor) -> Optional[ParsedEmailMessage]:
        subject = graph_message.get("subject", "") or ""
        from_obj = ((graph_message.get("from") or {}).get("emailAddress") or {})
        from_name = from_obj.get("name", "") or ""
        from_email = (from_obj.get("address", "") or "").lower()
        extracted_links = self._parser.extract_links(((graph_message.get("body") or {}).get("content") or "") or "")

        received_at_raw = graph_message.get("receivedDateTime", "")
        try:
            received_at = datetime.fromisoformat(received_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        body = parsed_vendor.latest_vendor_turn or parsed_vendor.latest_operator_turn or subject
        return ParsedEmailMessage(
            source_provider="microsoft",
            source_message_id=graph_message["id"],
            source_thread_id=graph_message.get("conversationId", "") or "",
            gmail_message_id=graph_message["id"],
            gmail_thread_id=graph_message.get("conversationId", "") or "",
            message_id_header=graph_message.get("internetMessageId", "") or "",
            guest_name=parsed_vendor.vendor_name or "Vendor",
            guest_email=parsed_vendor.vendor_email or from_email,
            sender_role=parsed_vendor.sender_role or "vendor",
            reply_channel_address="",
            system_generated=True,
            system_event_type=parsed_vendor.system_event_type or "vendor_ops_email",
            subject=subject,
            body=body,
            latest_guest_message="",
            latest_operator_message=parsed_vendor.latest_operator_turn or "",
            conversation_context="",
            full_body=((graph_message.get("body") or {}).get("content") or body),
            extracted_links=extracted_links,
            asks=[],
            platform="direct",
            is_inquiry=False,
            lifecycle_stage="ops_vendor",
            parser_source=parsed_vendor.parser_source,
            property_name=parsed_vendor.property_name_hint or "",
            property_code="",
            platform_listing_id="",
            platform_unit_id="",
            source_interaction_id="",
            source_property_id="",
            reservation_id="",
            requested_check_in=None,
            requested_check_out=None,
            requested_guests=None,
            received_at=received_at,
            raw_from=f"{from_name} <{from_email}>".strip(),
        )

    def _adapt_direct_graph_inquiry(self, graph_message: Dict[str, Any], parsed_direct) -> Optional[ParsedEmailMessage]:
        subject = graph_message.get("subject", "") or ""
        from_obj = ((graph_message.get("from") or {}).get("emailAddress") or {})
        from_name = from_obj.get("name", "") or ""
        from_email = (from_obj.get("address", "") or "").lower()
        extracted_links = self._parser.extract_links(((graph_message.get("body") or {}).get("content") or "") or "")

        received_at_raw = graph_message.get("receivedDateTime", "")
        try:
            received_at = datetime.fromisoformat(received_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except Exception:
            received_at = datetime.utcnow()

        requested_guests = None
        if parsed_direct.guests_adults is not None or parsed_direct.guests_children is not None:
            requested_guests = (parsed_direct.guests_adults or 0) + (parsed_direct.guests_children or 0)

        body = parsed_direct.latest_guest_turn or parsed_direct.message_body or parsed_direct.latest_operator_turn or ""
        if len(body.strip()) < 10:
            return None

        return ParsedEmailMessage(
            source_provider="microsoft",
            source_message_id=graph_message["id"],
            source_thread_id=graph_message.get("conversationId", "") or "",
            gmail_message_id=graph_message["id"],
            gmail_thread_id=graph_message.get("conversationId", "") or "",
            message_id_header=graph_message.get("internetMessageId", "") or "",
            guest_name=parsed_direct.guest_name or from_name or "Guest",
            guest_email=parsed_direct.guest_email or from_email,
            sender_role=parsed_direct.sender_role or "guest",
            reply_channel_address=parsed_direct.reply_channel_address or "",
            subject=subject,
            body=body,
            latest_guest_message=parsed_direct.latest_guest_turn or body,
            latest_operator_message=parsed_direct.latest_operator_turn or "",
            conversation_context=parsed_direct.prior_thread_context or "",
            full_body=body,
            extracted_links=extracted_links,
            asks=list(parsed_direct.asks or []),
            platform="direct",
            is_inquiry=True,
            lifecycle_stage=parsed_direct.lifecycle_stage or "pre_booking",
            parser_source=parsed_direct.parser_source,
            property_name=parsed_direct.property_name_hint or "",
            property_code="",
            platform_listing_id="",
            platform_unit_id="",
            requested_check_in=parsed_direct.check_in,
            requested_check_out=parsed_direct.check_out,
            requested_guests=requested_guests,
            received_at=received_at,
            raw_from=f"{from_name} <{from_email}>".strip(),
        )


class MicrosoftReplySender(EmailReplySenderBase):
    provider_name = "Microsoft"

    async def reply(
        self,
        thread_id: str,
        in_reply_to: str,
        to_address: str,
        to_name: str,
        subject: str,
        body: str,
        operator_name: str,
        from_email: Optional[str] = None,
    ) -> bool:
        try:
            token = await self.token_manager.get_access_token()
            headers = {
                **self.token_manager.auth_header(token),
                "Content-Type": "application/json",
            }
            if in_reply_to:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{MS_GRAPH_BASE}/me/messages/{in_reply_to}/reply",
                        headers=headers,
                        json={"comment": body},
                    )
                    resp.raise_for_status()
                    self._log_send_success(to_address, thread_id or in_reply_to or "")
                    return True

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{MS_GRAPH_BASE}/me/sendMail",
                    headers=headers,
                    json={
                        "message": {
                            "subject": subject,
                            "body": {
                                "contentType": "Text",
                                "content": body,
                            },
                            "toRecipients": [{
                                "emailAddress": {
                                    "address": to_address,
                                    "name": to_name or to_address,
                                }
                            }],
                        },
                        "saveToSentItems": True,
                    },
                )
                resp.raise_for_status()
                self._log_send_success(to_address, thread_id or "")
                return True
        except Exception as e:
            self._log_send_failure(e)
            return False
