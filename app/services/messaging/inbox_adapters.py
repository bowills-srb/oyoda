from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable
from uuid import UUID

from app.services.messaging.inbound_transport import (
    InboundTransportCapability,
    get_inbound_transport_capability,
)


@dataclass(frozen=True)
class InboxAdapterConfig:
    operator_id: str
    company_id: UUID
    watched_email: str
    refresh_token: str
    provider: str = "gmail"
    poll_label: str = "INBOX"
    processed_label: str = "Oyvoda-Processed"


class InboxAdapterBuildError(RuntimeError):
    pass


@runtime_checkable
class InboxAdapter(Protocol):
    operator_id: str
    company_id: UUID
    watched_email: str

    @property
    def provider(self) -> str: ...
    def transport_capability(self) -> InboundTransportCapability: ...

    async def poll(self): ...
    async def poll_with_mode(self, query_mode: str = "unread"): ...
    async def poll_message_ids(self, message_ids: list[str], *, query_mode: str = "specific_ids"): ...


@runtime_checkable
class OutboundReplyAdapter(Protocol):
    async def reply(
        self,
        thread_id: str,
        in_reply_to: str,
        to_address: str,
        to_name: str,
        subject: str,
        body: str,
        operator_name: str,
        from_email: str | None = None,
    ) -> bool: ...


def _normalize_provider(provider: str) -> str:
    value = (provider or "gmail").strip().lower()
    if value in {"google", "gmail"}:
        return "gmail"
    if value in {"microsoft", "outlook", "office365", "m365"}:
        return "microsoft"
    return value or "gmail"


def build_inbox_adapter(
    config: InboxAdapterConfig,
    *,
    db=None,
) -> Optional[InboxAdapter]:
    provider = _normalize_provider(config.provider)
    if provider == "gmail":
        from app.services.integrations.gmail_inbox_poller import GmailInboxPoller, GmailTokenManager

        client_id = os.getenv("GMAIL_CLIENT_ID", "")
        client_secret = os.getenv("GMAIL_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return None
        token_manager = GmailTokenManager(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=config.refresh_token,
        )
        return GmailInboxPoller(
            operator_id=config.operator_id,
            company_id=config.company_id,
            token_manager=token_manager,
            watched_email=config.watched_email,
            poll_label=config.poll_label,
            processed_label=config.processed_label,
            db=db,
        )

    if provider == "microsoft":
        from app.services.integrations.microsoft_inbox_poller import MicrosoftInboxPoller, MicrosoftTokenManager

        client_id = os.getenv("MICROSOFT_CLIENT_ID", "")
        client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return None
        token_manager = MicrosoftTokenManager(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=config.refresh_token,
        )
        return MicrosoftInboxPoller(
            operator_id=config.operator_id,
            company_id=config.company_id,
            token_manager=token_manager,
            watched_email=config.watched_email,
            poll_label=config.poll_label,
            processed_label=config.processed_label,
            db=db,
        )

    raise InboxAdapterBuildError(f"Unsupported inbox provider: {provider}")


def build_reply_adapter(config: InboxAdapterConfig) -> Optional[OutboundReplyAdapter]:
    provider = _normalize_provider(config.provider)
    if provider == "gmail":
        from app.services.integrations.gmail_inbox_poller import GmailReplySender, GmailTokenManager

        client_id = os.getenv("GMAIL_CLIENT_ID", "")
        client_secret = os.getenv("GMAIL_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return None
        token_manager = GmailTokenManager(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=config.refresh_token,
        )
        return GmailReplySender(token_manager)

    if provider == "microsoft":
        from app.services.integrations.microsoft_inbox_poller import MicrosoftReplySender, MicrosoftTokenManager

        client_id = os.getenv("MICROSOFT_CLIENT_ID", "")
        client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "")
        if not client_id or not client_secret:
            return None
        token_manager = MicrosoftTokenManager(
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=config.refresh_token,
        )
        return MicrosoftReplySender(token_manager)

    raise InboxAdapterBuildError(f"Unsupported inbox provider: {provider}")


def get_inbox_transport_capability(provider: str) -> InboundTransportCapability:
    return get_inbound_transport_capability(provider)
