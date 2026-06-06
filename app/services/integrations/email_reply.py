from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EmailReplySenderBase:
    """Provider-agnostic base for outbound email replies."""

    provider_name = "email"

    def __init__(self, token_manager):
        self.token_manager = token_manager

    def _build_rfc2822_email(
        self,
        *,
        to_address: str,
        to_name: str,
        subject: str,
        body: str,
        in_reply_to: str,
        references: str,
        from_email: str,
        from_name: str,
    ) -> str:
        lines = []
        if from_email:
            lines.append(f"From: {from_name} <{from_email}>")
        if to_name:
            lines.append(f"To: {to_name} <{to_address}>")
        else:
            lines.append(f"To: {to_address}")
        lines.append(f"Subject: {subject}")
        if in_reply_to:
            lines.append(f"In-Reply-To: {in_reply_to}")
        if references:
            lines.append(f"References: {references}")
        lines.append("Content-Type: text/plain; charset=utf-8")
        lines.append("MIME-Version: 1.0")
        lines.append("")
        lines.append(body)
        return "\r\n".join(lines)

    def _log_send_success(self, to_address: str, thread_id: str) -> None:
        logger.info("[%sReply] Reply sent to %s in thread %s", self.provider_name, to_address, thread_id)

    def _log_send_failure(self, exc: Exception) -> None:
        logger.error("[%sReply] Send failed: %s", self.provider_name, exc)
