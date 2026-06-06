from __future__ import annotations

from typing import Callable, Dict, Type

from app.services.transport.base import ChannelTransport
from app.services.transport.credentials import (
    OperatorCredentialRecord,
    OperatorCredentialStore,
    normalize_channel,
)


class UnknownTransportProviderError(RuntimeError):
    """Raised when no transport provider is registered for a channel key."""


class MissingTransportCredentialsError(RuntimeError):
    """Raised when a provider is known but the operator has no credentials."""


TransportBuilder = Callable[[OperatorCredentialRecord], ChannelTransport]


class ChannelTransportFactory:
    """Registry-backed factory for transport providers.

    The factory depends on an `OperatorCredentialStore` rather than knowing
    where each provider's credentials live. That keeps channel-specific
    credential retrieval out of the factory and lets providers interpret their
    own credential blobs.
    """

    _registry: Dict[str, TransportBuilder] = {}

    @classmethod
    def register(cls, channel: str, builder: TransportBuilder) -> None:
        cls._registry[normalize_channel(channel)] = builder

    @classmethod
    def registered_channels(cls) -> tuple[str, ...]:
        return tuple(sorted(cls._registry.keys()))

    @classmethod
    async def build(
        cls,
        *,
        channel: str,
        operator_id: str,
        credential_store: OperatorCredentialStore,
        tenant_id: str | None = None,
    ) -> ChannelTransport:
        normalized_channel = normalize_channel(channel)
        builder = cls._registry.get(normalized_channel)
        if not builder:
            raise UnknownTransportProviderError(
                f"No transport provider registered for channel '{normalized_channel}'"
            )

        record = await credential_store.get_transport_credentials(
            operator_id=operator_id,
            channel=normalized_channel,
            tenant_id=tenant_id,
        )
        if not record:
            raise MissingTransportCredentialsError(
                f"No transport credentials configured for operator={operator_id} channel={normalized_channel}"
            )

        return builder(record)
