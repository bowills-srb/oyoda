from __future__ import annotations

import asyncio

from app.services.operator.scope_service import OperatorScopeService


class _FakeMappingsResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeFetchResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    def __init__(self, scripted):
        self.scripted = list(scripted)
        self.rollbacks = 0

    async def execute(self, statement, params=None):
        action = self.scripted.pop(0)
        kind, payload = action
        if kind == "mappings":
            return _FakeMappingsResult(payload)
        if kind == "fetchall":
            return _FakeFetchResult(payload)
        raise AssertionError(f"Unknown scripted action: {kind}")

    async def scalar(self, statement, params=None):
        kind, payload = self.scripted.pop(0)
        assert kind == "scalar"
        return payload

    async def rollback(self):
        self.rollbacks += 1


def test_visible_property_codes_returns_none_for_owner():
    service = OperatorScopeService()
    db = _FakeSession([])

    result = asyncio.run(
        service.visible_property_codes(
            db,
            "e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            "11111111-1111-1111-1111-111111111111",
            "owner",
        )
    )

    assert result is None


def test_visible_property_codes_collects_property_and_portfolio_scope():
    service = OperatorScopeService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {"scope_type": "property", "portfolio_id": None, "property_external_id": "LANIER-1"},
                {"scope_type": "portfolio", "portfolio_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "property_external_id": None},
            ]),
            ("scalar", True),
            ("fetchall", [("BEACH-1",), ("BEACH-2",)]),
        ]
    )

    result = asyncio.run(
        service.visible_property_codes(
            db,
            "e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            "11111111-1111-1111-1111-111111111111",
            "staff",
        )
    )

    assert result == {"LANIER-1", "BEACH-1", "BEACH-2"}


def test_scope_profile_uses_manager_defaults_without_scope_rows():
    service = OperatorScopeService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", []),
        ]
    )

    result = asyncio.run(
        service.get_scope_profile(
            db,
            "e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            "11111111-1111-1111-1111-111111111111",
            "manager",
        )
    )

    assert result["visible_property_codes"] is None
    assert result["can_assign"] is True
    assert result["can_manage_vendors"] is True
    assert result["can_manage_settings"] is True
    assert result["has_scopes"] is False


def test_scope_profile_uses_explicit_scope_permissions_when_present():
    service = OperatorScopeService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "scope_type": "property",
                    "portfolio_id": None,
                    "property_external_id": "LANIER-1",
                    "can_assign": False,
                    "can_manage_vendors": True,
                    "can_manage_settings": False,
                    "can_view": True,
                },
                {
                    "scope_type": "portfolio",
                    "portfolio_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "property_external_id": None,
                    "can_assign": True,
                    "can_manage_vendors": False,
                    "can_manage_settings": False,
                    "can_view": True,
                },
            ]),
            ("scalar", True),
            ("fetchall", [("BEACH-1",)]),
        ]
    )

    result = asyncio.run(
        service.get_scope_profile(
            db,
            "e07980b2-a990-4b24-91d1-c8cb71ab70e1",
            "11111111-1111-1111-1111-111111111111",
            "staff",
        )
    )

    assert result["has_scopes"] is True
    assert result["visible_property_codes"] == {"LANIER-1", "BEACH-1"}
    assert result["can_assign"] is True
    assert result["can_manage_vendors"] is True
    assert result["can_manage_settings"] is False


def test_list_portfolios_includes_property_external_ids():
    service = OperatorScopeService()
    db = _FakeSession(
        [
            ("scalar", True),
            ("mappings", [
                {
                    "portfolio_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "portfolio_key": "beach_ops",
                    "display_name": "Beach Ops",
                    "description": "Beachfront team",
                    "active": True,
                    "property_count": 2,
                    "property_external_ids": ["BEACH-1", "BEACH-2"],
                }
            ]),
        ]
    )

    result = asyncio.run(
        service.list_portfolios(
            db,
            "e07980b2-a990-4b24-91d1-c8cb71ab70e1",
        )
    )

    assert result == [
        {
            "portfolio_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "portfolio_key": "beach_ops",
            "display_name": "Beach Ops",
            "description": "Beachfront team",
            "active": True,
            "property_count": 2,
            "property_external_ids": ["BEACH-1", "BEACH-2"],
        }
    ]
