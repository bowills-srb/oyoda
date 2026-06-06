from __future__ import annotations

import pytest

from app.services.transport.base import ChannelTransport, TransportCapability
from app.services.transport.credentials import OperatorCredentialRecord, OperatorCredentialStore
from app.services.transport.factory import (
    ChannelTransportFactory,
    MissingTransportCredentialsError,
    UnknownTransportProviderError,
)


class _FakeCredentialStore(OperatorCredentialStore):
    def __init__(self, record: OperatorCredentialRecord | None):
        self.record = record
        self.calls: list[tuple[str, str, str | None]] = []

    async def get_transport_credentials(
        self,
        *,
        operator_id: str,
        channel: str,
        tenant_id: str | None = None,
    ) -> OperatorCredentialRecord | None:
        self.calls.append((operator_id, channel, tenant_id))
        return self.record


class _FakeTransport(ChannelTransport):
    def __init__(self, record: OperatorCredentialRecord):
        self.record = record

    @property
    def channel(self) -> str:
        return "fake_channel"

    @property
    def capabilities(self) -> frozenset[TransportCapability]:
        return frozenset({TransportCapability.GET_MESSAGE})


def _build_fake_transport(record: OperatorCredentialRecord) -> _FakeTransport:
    return _FakeTransport(record)


@pytest.mark.asyncio
async def test_factory_builds_registered_provider() -> None:
    original = ChannelTransportFactory._registry.copy()
    try:
        ChannelTransportFactory.register("fake_channel", _build_fake_transport)
        record = OperatorCredentialRecord(
            operator_id="op-123",
            channel="fake_channel",
            tenant_id="tenant-abc",
        )
        store = _FakeCredentialStore(record)

        transport = await ChannelTransportFactory.build(
            channel="fake_channel",
            operator_id="op-123",
            credential_store=store,
            tenant_id="tenant-abc",
        )

        assert isinstance(transport, _FakeTransport)
        assert transport.record is record
        assert store.calls == [("op-123", "fake_channel", "tenant-abc")]
    finally:
        ChannelTransportFactory._registry = original


@pytest.mark.asyncio
async def test_factory_raises_for_unknown_channel() -> None:
    store = _FakeCredentialStore(None)
    with pytest.raises(UnknownTransportProviderError):
        await ChannelTransportFactory.build(
            channel="definitely_missing",
            operator_id="op-123",
            credential_store=store,
        )


@pytest.mark.asyncio
async def test_factory_raises_for_missing_credentials() -> None:
    original = ChannelTransportFactory._registry.copy()
    try:
        ChannelTransportFactory.register("fake_channel", _build_fake_transport)
        store = _FakeCredentialStore(None)

        with pytest.raises(MissingTransportCredentialsError):
            await ChannelTransportFactory.build(
                channel="fake_channel",
                operator_id="op-123",
                credential_store=store,
            )
    finally:
        ChannelTransportFactory._registry = original


def test_registered_channels_reports_registered_set() -> None:
    original = ChannelTransportFactory._registry.copy()
    try:
        ChannelTransportFactory.register("zeta_channel", _build_fake_transport)
        ChannelTransportFactory.register("alpha_channel", _build_fake_transport)
        channels = ChannelTransportFactory.registered_channels()
        assert "alpha_channel" in channels
        assert "zeta_channel" in channels
        assert channels == tuple(sorted(channels))
    finally:
        ChannelTransportFactory._registry = original
