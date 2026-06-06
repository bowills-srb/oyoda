from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.operator_policies.discount_rules import validate_discount_policies


def test_valid_next_night_extension_rule():
    payload = {
        "rules": [
            {
                "id": "next-night-extension",
                "type": "next_night_extension",
                "active": True,
                "condition": {"kind": "gap_night_available"},
                "offer": {"discount_pct": 15},
                "notes": "15% off next night if unbooked after checkout",
            }
        ]
    }
    parsed = validate_discount_policies(payload)
    assert parsed["rules"][0]["id"] == "next-night-extension"


def test_invalid_discount_pct_rejected():
    with pytest.raises(ValidationError):
        validate_discount_policies(
            {"rules": [{"id": "x", "type": "next_night_extension", "condition": {"kind": "gap_night_available"}, "offer": {"discount_pct": 101}}]}
        )


def test_duplicate_rule_ids_rejected():
    with pytest.raises(ValidationError):
        validate_discount_policies(
            {
                "rules": [
                    {"id": "dup", "type": "next_night_extension", "condition": {"kind": "gap_night_available"}, "offer": {"discount_pct": 10}},
                    {"id": "dup", "type": "repeat_guest_discount", "condition": {"kind": "repeat_guest"}, "offer": {"discount_pct": 5}},
                ]
            }
        )


def test_empty_rules_list_valid():
    assert validate_discount_policies({"rules": []}) == {"rules": []}


def test_unknown_rule_type_rejected():
    with pytest.raises(ValidationError):
        validate_discount_policies(
            {"rules": [{"id": "x", "type": "mystery", "condition": {"kind": "gap_night_available"}, "offer": {"discount_pct": 10}}]}
        )
