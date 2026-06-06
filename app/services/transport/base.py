from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class MessageDirection(str, Enum):
    """Closed set describing message flow relative to the operator inbox."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class TransportCapability(str, Enum):
    """Capabilities a transport provider may declare and support."""

    POLL_INBOX = "poll_inbox"
    SEND_REPLY = "send_reply"
    FETCH_THREAD_HISTORY = "fetch_thread_history"
    MARK_READ = "mark_read"
    GET_MESSAGE = "get_message"


class NotSupportedError(RuntimeError):
    """Raised when a transport operation is unavailable for a provider."""


@dataclass(frozen=True)
class NormalizedParty:
    """Normalized sender/recipient identity across channel types."""

    email: Optional[str] = None
    phone: Optional[str] = None
    display_name: str = ""
    provider_user_ref: Optional[str] = None


@dataclass(frozen=True)
class Attachment:
    """Reference metadata for a provider attachment.

    Attachments are intentionally lazy. Callers receive lightweight metadata
    and a provider attachment reference rather than eager bytes.
    """

    filename: str = ""
    mime_type: str = ""
    size_bytes: Optional[int] = None
    provider_attachment_ref: Optional[str] = None
    inline: bool = False
    content_id: Optional[str] = None


@dataclass(frozen=True)
class NormalizedMessage:
    """Provider-agnostic message shape shared across transport implementations.

    Notes
    -----
    - `channel` is a stable provider key string (`gmail`, `outlook`,
      `escapia_inbox`, etc.), not an enum. This keeps the transport contract
      extensible: new providers can register without editing this core file.
    - `body_text` is always a string. Providers that only expose HTML must
      derive text at the transport boundary so downstream callers never need
      `None` checks for the primary body field.
    - See the field docstrings on `sent_at` and `received_at` for their
      distinct semantics; callers should not substitute one for the other.
    """

    channel: str
    message_ref: str
    thread_ref: str
    direction: MessageDirection
    sender: NormalizedParty
    recipient: NormalizedParty
    subject: Optional[str] = None
    thread_subject: Optional[str] = None
    body_text: str = ""
    body_html: Optional[str] = None
    sent_at: Optional[datetime] = None
    """When the sender's system says the message was sent.

    This is the authoritative timestamp for conversational ordering within a
    thread and should be preferred for chronology when available.
    """

    received_at: Optional[datetime] = None
    """When Oyvoda observed the message (poll time / webhook time).

    This is operational metadata for latency, SLA, and debugging. Callers
    should not substitute it for `sent_at` when reconstructing conversation
    history unless no sender-side timestamp exists.
    """

    in_reply_to_ref: Optional[str] = None
    provider_message_type: Optional[str] = None
    attachments: Sequence[Attachment] = field(default_factory=tuple)
    raw_provider_payload: Optional[Mapping[str, Any]] = None


class ChannelTransport(ABC):
    """Abstract transport contract for inbox-like message channels."""

    @property
    @abstractmethod
    def channel(self) -> str:
        """Stable provider key such as `gmail` or `escapia_inbox`."""

    @property
    @abstractmethod
    def capabilities(self) -> frozenset[TransportCapability]:
        """Declared provider capabilities for caller-side planning."""

    def _require(self, capability: TransportCapability) -> None:
        """Defensive backstop for shared implementations.

        Callers should primarily branch on `capabilities`, but shared base or
        adapter logic may use this helper to fail clearly if invoked anyway.
        """

        if capability not in self.capabilities:
            raise NotSupportedError(
                f"{self.__class__.__name__} does not support {capability.value}"
            )

    async def poll_inbox(
        self,
        *,
        query_mode: str = "unread",
        limit: Optional[int] = None,
    ) -> list[NormalizedMessage]:
        self._require(TransportCapability.POLL_INBOX)
        raise NotSupportedError(f"{self.__class__.__name__} must override poll_inbox()")

    async def get_message(self, message_ref: str) -> Optional[NormalizedMessage]:
        self._require(TransportCapability.GET_MESSAGE)
        raise NotSupportedError(f"{self.__class__.__name__} must override get_message()")

    async def fetch_thread_history(self, thread_ref: str) -> list[NormalizedMessage]:
        self._require(TransportCapability.FETCH_THREAD_HISTORY)
        raise NotSupportedError(
            f"{self.__class__.__name__} must override fetch_thread_history()"
        )

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
        self._require(TransportCapability.SEND_REPLY)
        raise NotSupportedError(f"{self.__class__.__name__} must override send_reply()")

    async def mark_read(self, message_ref: str) -> None:
        self._require(TransportCapability.MARK_READ)
        raise NotSupportedError(f"{self.__class__.__name__} must override mark_read()")
