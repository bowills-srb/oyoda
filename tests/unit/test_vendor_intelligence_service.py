from __future__ import annotations

from app.services.operator.vendor_intelligence_service import VendorIntelligenceService


def test_normalize_metadata_coerces_lists_and_flags():
    service = VendorIntelligenceService()

    result = service.normalize_metadata(
        {
            "manufacturer_tags": "carrier, trane",
            "supported_issue_tags": ["hvac", "emergency"],
            "warranty_provider_tags": "carrier",
            "warranty_capable": True,
            "emergency_capable": True,
            "response_sla_minutes": 30,
        }
    )

    assert result["manufacturer_tags"] == ["carrier", "trane"]
    assert result["supported_issue_tags"] == ["hvac", "emergency"]
    assert result["warranty_provider_tags"] == ["carrier"]
    assert result["warranty_capable"] is True
    assert result["emergency_capable"] is True
    assert result["response_sla_minutes"] == 30


def test_score_vendor_rewards_emergency_and_warranty_fit():
    service = VendorIntelligenceService()
    vendor = {
        "category_slug": "maintenance",
        "priority": 1,
        "operational_metadata": {
            "manufacturer_tags": ["carrier"],
            "warranty_provider_tags": ["carrier"],
            "supported_issue_tags": ["hvac", "emergency"],
            "warranty_capable": True,
            "emergency_capable": True,
            "response_sla_minutes": 30,
        },
    }

    score = service.score_vendor(
        vendor,
        text_blob="guest says the carrier hvac is out and this feels urgent",
        issue_tags=["hvac", "emergency"],
        manufacturer_tags=["carrier"],
        emergency=True,
        warranty_sensitive=True,
    )

    assert score >= 40


def test_normalize_property_profile_extracts_warranty_and_system_context():
    service = VendorIntelligenceService()

    profile = service.normalize_property_profile(
        {
            "property_code": "LANIER-1",
            "thermostat_type": "Ecobee smart thermostat",
            "known_issues": [{"description": "Carrier HVAC has intermittent cooling issue"}],
            "warranty_items": [{"item": "Carrier condenser under warranty"}],
            "emergency_contact": "Ops Lead",
        }
    )

    assert profile["property_code"] == "lanier-1"
    assert profile["warranty_sensitive"] is True
    assert "carrier" in profile["manufacturer_tags"]
    assert "hvac" in profile["system_tags"]
    assert "carrier" in profile["warranty_provider_tags"]


def test_evaluate_vendor_marks_emergency_override_when_warranty_safe_path_missing():
    service = VendorIntelligenceService()
    vendor = {
        "category_slug": "maintenance",
        "priority": 2,
        "operational_metadata": {
            "manufacturer_tags": ["carrier"],
            "supported_issue_tags": ["hvac", "emergency"],
            "emergency_capable": True,
            "after_hours_available": True,
            "warranty_capable": False,
            "backup_rank": 2,
        },
    }

    result = service.evaluate_vendor(
        vendor,
        text_blob="guest says the carrier hvac is out and it smells unsafe",
        property_profile={
            "property_code": "LANIER-1",
            "warranty_items": [{"item": "Carrier HVAC under warranty"}],
            "known_issues": [{"description": "Carrier unit"}],
        },
        issue_tags=["hvac", "emergency"],
        emergency=True,
        warranty_sensitive=True,
    )

    assert result["recommended"] is True
    assert result["decision_mode"] == "emergency_override"
    assert "Emergency-capable vendor" in result["reasons"]
    assert "Emergency override may bypass warranty-safe path" in result["concerns"]
