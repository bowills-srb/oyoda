from __future__ import annotations

import json
import re
from typing import Any


_MANUFACTURER_ALIASES = {
    "carrier": ["carrier"],
    "trane": ["trane"],
    "lennox": ["lennox"],
    "rheem": ["rheem"],
    "ruud": ["ruud"],
    "goodman": ["goodman"],
    "amana": ["amana"],
    "daikin": ["daikin"],
    "york": ["york"],
    "mitsubishi": ["mitsubishi"],
    "bosch": ["bosch"],
    "ge": ["general electric", "ge "],
    "whirlpool": ["whirlpool"],
    "frigidaire": ["frigidaire"],
    "maytag": ["maytag"],
    "navien": ["navien"],
    "ao smith": ["ao smith", "a.o. smith"],
}


class VendorIntelligenceService:
    def normalize_metadata(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        raw = raw if isinstance(raw, dict) else {}

        def _list(key: str) -> list[str]:
            value = raw.get(key)
            if isinstance(value, list):
                return [str(item).strip().lower() for item in value if str(item).strip()]
            if isinstance(value, str):
                parts = [part.strip().lower() for part in re.split(r"[,\n|/;]+", value) if part.strip()]
                return parts
            return []

        return {
            "manufacturer_tags": _list("manufacturer_tags"),
            "excluded_manufacturer_tags": _list("excluded_manufacturer_tags"),
            "warranty_provider_tags": _list("warranty_provider_tags"),
            "supported_issue_tags": _list("supported_issue_tags"),
            "supported_system_tags": _list("supported_system_tags"),
            "service_area_tags": _list("service_area_tags"),
            "preferred_property_codes": _list("preferred_property_codes"),
            "warranty_capable": bool(raw.get("warranty_capable", False)),
            "warranty_only": bool(raw.get("warranty_only", False)),
            "emergency_capable": bool(raw.get("emergency_capable", False)),
            "emergency_override_only": bool(raw.get("emergency_override_only", False)),
            "after_hours_available": bool(raw.get("after_hours_available", False)),
            "backup_rank": max(0, int(raw.get("backup_rank", 0) or 0)),
            "response_sla_minutes": max(0, int(raw.get("response_sla_minutes", 0) or 0)),
            "approval_mode": str(raw.get("approval_mode") or "standard").strip().lower() or "standard",
            "cost_tier": str(raw.get("cost_tier") or "standard").strip().lower() or "standard",
            "notes": str(raw.get("notes") or "").strip(),
        }

    def normalize_property_profile(self, raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        raw = raw if isinstance(raw, dict) else {}

        warranty_items = raw.get("warranty_items")
        if isinstance(warranty_items, str):
            try:
                warranty_items = json.loads(warranty_items)
            except Exception:
                warranty_items = [warranty_items]
        warranty_items = warranty_items if isinstance(warranty_items, list) else []

        known_issues = raw.get("known_issues")
        if isinstance(known_issues, str):
            try:
                known_issues = json.loads(known_issues)
            except Exception:
                known_issues = [known_issues]
        known_issues = known_issues if isinstance(known_issues, list) else []

        collected_text = " ".join(
            [
                str(raw.get("thermostat_type") or ""),
                str(raw.get("hvac_instructions") or ""),
                str(raw.get("general_notes") or ""),
                " ".join(self._stringify_items(known_issues)),
                " ".join(self._stringify_items(warranty_items)),
            ]
        ).lower()

        manufacturer_tags = self._extract_manufacturer_tags(collected_text)
        system_tags = self._issue_tags_from_text(collected_text)
        warranty_provider_tags = self._extract_manufacturer_tags(" ".join(self._stringify_items(warranty_items)).lower())

        return {
            "property_code": str(raw.get("property_code") or "").strip().lower(),
            "property_id": str(raw.get("property_id") or raw.get("id") or "").strip(),
            "thermostat_type": str(raw.get("thermostat_type") or "").strip(),
            "emergency_contact": str(raw.get("emergency_contact") or "").strip(),
            "manufacturer_tags": manufacturer_tags,
            "system_tags": system_tags,
            "known_issue_tags": self._issue_tags_from_text(" ".join(self._stringify_items(known_issues)).lower()),
            "warranty_sensitive": bool(warranty_items),
            "warranty_provider_tags": warranty_provider_tags,
            "warranty_items": self._stringify_items(warranty_items),
            "notes": collected_text,
        }

    def evaluate_vendor(
        self,
        vendor: dict[str, Any],
        *,
        text_blob: str,
        issue_tags: list[str] | None = None,
        manufacturer_tags: list[str] | None = None,
        property_code: str | None = None,
        property_profile: dict[str, Any] | None = None,
        emergency: bool = False,
        warranty_sensitive: bool = False,
    ) -> dict[str, Any]:
        slug = str(vendor.get("category_slug") or "").lower()
        metadata = self.normalize_metadata(vendor.get("operational_metadata"))
        property_profile = self.normalize_property_profile(property_profile)
        issue_tags = self._normalize_tags(issue_tags or self._issue_tags_from_text(text_blob))
        property_manufacturers = property_profile["manufacturer_tags"]
        manufacturer_tags = self._normalize_tags((manufacturer_tags or []) + property_manufacturers)
        property_code = str(property_code or property_profile.get("property_code") or "").strip().lower()
        warranty_sensitive = bool(warranty_sensitive or property_profile.get("warranty_sensitive"))
        emergency = bool(emergency)

        score = 0
        reasons: list[str] = []
        concerns: list[str] = []
        blocked_reasons: list[str] = []

        if slug == "maintenance":
            score += 8
            reasons.append("Maintenance vendor fits issue class")
        if slug in {"cleaning", "housekeeping", "linen", "laundry"}:
            score += 7
            reasons.append("Turnover vendor fits cleaning workflow")
        if slug == "transportation":
            score += 4
            reasons.append("Transportation vendor fits experience workflow")

        supported_issue_tags = set(metadata["supported_issue_tags"])
        supported_system_tags = set(metadata["supported_system_tags"])
        vendor_manufacturers = set(metadata["manufacturer_tags"])
        excluded_manufacturers = set(metadata["excluded_manufacturer_tags"])
        preferred_property_codes = set(metadata["preferred_property_codes"])
        warranty_provider_tags = set(metadata["warranty_provider_tags"])
        property_warranty_providers = set(property_profile["warranty_provider_tags"])

        if metadata["emergency_override_only"] and not emergency:
            blocked_reasons.append("Emergency-only vendor suppressed for non-emergency workflow")
        if metadata["warranty_only"] and not warranty_sensitive:
            blocked_reasons.append("Warranty-only vendor suppressed for non-warranty workflow")

        if property_code and preferred_property_codes and property_code in preferred_property_codes:
            score += 10
            reasons.append("Preferred for this property")

        if issue_tags and supported_issue_tags:
            overlap = set(issue_tags) & supported_issue_tags
            if overlap:
                score += 6 * len(overlap)
                reasons.append(f"Issue fit: {', '.join(sorted(overlap))}")
            else:
                score -= 5
                concerns.append("Does not explicitly cover this issue family")

        if manufacturer_tags and vendor_manufacturers:
            overlap = set(manufacturer_tags) & vendor_manufacturers
            if overlap:
                score += 7 * len(overlap)
                reasons.append(f"Manufacturer fit: {', '.join(sorted(overlap))}")
            else:
                score -= 8 if warranty_sensitive else 4
                concerns.append("Manufacturer mismatch for property system")

        if manufacturer_tags and excluded_manufacturers and (set(manufacturer_tags) & excluded_manufacturers):
            blocked_reasons.append("Vendor excludes this property's manufacturer/system family")

        if property_warranty_providers and warranty_provider_tags:
            overlap = property_warranty_providers & warranty_provider_tags
            if overlap:
                score += 8
                reasons.append("Warranty provider match")
            elif warranty_sensitive:
                score -= 6
                concerns.append("Warranty provider mismatch")

        if "hvac" in supported_system_tags and re.search(r"\bac\b|\bhvac\b|heat|thermostat", text_blob):
            score += 8
            reasons.append("HVAC system match")
        if "plumbing" in supported_system_tags and re.search(r"leak|water|plumb|toilet|shower|sink", text_blob):
            score += 8
            reasons.append("Plumbing system match")
        if "lock" in supported_system_tags and re.search(r"lock|door code|lockbox|can.t get in|cant get in", text_blob):
            score += 7
            reasons.append("Access system match")
        if slug == "maintenance" and re.search(r"broken|repair|not working|maintenance|electric|ac\b|hvac|lock", text_blob):
            score += 8
        if slug in {"cleaning", "housekeeping", "linen", "laundry"} and re.search(r"clean|dirty|turnover|linens|laundry|checkout", text_blob):
            score += 8
        if slug == "transportation" and re.search(r"airport|ride|shuttle|transport|pickup|dropoff|car", text_blob):
            score += 8

        if emergency:
            if metadata["emergency_capable"]:
                score += 10
                reasons.append("Emergency-capable vendor")
            else:
                score -= 10
                concerns.append("Not marked emergency-capable")
            if metadata["after_hours_available"]:
                score += 6
                reasons.append("After-hours capable")
        if warranty_sensitive:
            if metadata["warranty_capable"]:
                score += 8
                reasons.append("Warranty-safe vendor")
            elif emergency and metadata["emergency_capable"]:
                score += 2
                concerns.append("Emergency override may bypass warranty-safe path")
            else:
                score -= 10
                concerns.append("Not marked warranty-safe")

        if metadata["backup_rank"]:
            score += max(0, 4 - metadata["backup_rank"])
            if metadata["backup_rank"] > 1:
                reasons.append(f"Backup tier {metadata['backup_rank']}")
        else:
            reasons.append("Primary/unspecified backup tier")
        if metadata["response_sla_minutes"]:
            sla_bonus = max(0, 6 - min(metadata["response_sla_minutes"], 180) // 30)
            score += sla_bonus
            if sla_bonus >= 3:
                reasons.append("Fast response SLA")
            elif metadata["response_sla_minutes"] > 180:
                concerns.append("Slow response SLA")

        score += max(0, 5 - int(vendor.get("priority") or 99))

        decision_mode = "standard"
        if emergency and warranty_sensitive and not metadata["warranty_capable"] and metadata["emergency_capable"]:
            decision_mode = "emergency_override"
        elif warranty_sensitive and metadata["warranty_capable"]:
            decision_mode = "warranty_safe"
        elif property_code and property_code in preferred_property_codes:
            decision_mode = "preferred_property"
        elif metadata["backup_rank"]:
            decision_mode = "backup"

        recommended = score > 0 and not blocked_reasons
        return {
            "recommended": recommended,
            "score": score if recommended else 0,
            "decision_mode": decision_mode,
            "reasons": reasons[:6],
            "concerns": concerns[:5],
            "blocked_reasons": blocked_reasons[:5],
            "operational_metadata": metadata,
            "property_profile": property_profile,
        }

    def recommend_vendors(
        self,
        vendors: list[dict[str, Any]],
        *,
        text_blob: str,
        issue_tags: list[str] | None = None,
        manufacturer_tags: list[str] | None = None,
        property_code: str | None = None,
        property_profile: dict[str, Any] | None = None,
        emergency: bool = False,
        warranty_sensitive: bool = False,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for vendor in vendors:
            evaluation = self.evaluate_vendor(
                vendor,
                text_blob=text_blob,
                issue_tags=issue_tags,
                manufacturer_tags=manufacturer_tags,
                property_code=property_code,
                property_profile=property_profile,
                emergency=emergency,
                warranty_sensitive=warranty_sensitive,
            )
            if not evaluation["recommended"]:
                continue
            item = dict(vendor)
            item["score"] = evaluation["score"]
            item["decision"] = {
                "mode": evaluation["decision_mode"],
                "reasons": evaluation["reasons"],
                "concerns": evaluation["concerns"],
                "blocked_reasons": evaluation["blocked_reasons"],
            }
            item["operational_metadata"] = evaluation["operational_metadata"]
            scored.append(item)
        scored.sort(key=lambda vendor: (-int(vendor.get("score") or 0), int(vendor.get("priority") or 999)))
        return scored[:limit]

    def score_vendor(
        self,
        vendor: dict[str, Any],
        *,
        text_blob: str,
        issue_tags: list[str] | None = None,
        manufacturer_tags: list[str] | None = None,
        property_code: str | None = None,
        emergency: bool = False,
        warranty_sensitive: bool = False,
        property_profile: dict[str, Any] | None = None,
    ) -> int:
        return int(
            self.evaluate_vendor(
                vendor,
                text_blob=text_blob,
                issue_tags=issue_tags,
                manufacturer_tags=manufacturer_tags,
                property_code=property_code,
                property_profile=property_profile,
                emergency=emergency,
                warranty_sensitive=warranty_sensitive,
            ).get("score")
            or 0
        )

    def infer_issue_tags(self, text_blob: str) -> list[str]:
        return self._issue_tags_from_text(text_blob)

    def _normalize_tags(self, values: list[str]) -> list[str]:
        return [str(value).strip().lower() for value in values if str(value).strip()]

    def _stringify_items(self, values: list[Any]) -> list[str]:
        items: list[str] = []
        for value in values:
            if isinstance(value, dict):
                items.extend(str(v).strip() for v in value.values() if str(v).strip())
            elif isinstance(value, list):
                items.extend(str(v).strip() for v in value if str(v).strip())
            elif str(value).strip():
                items.append(str(value).strip())
        return items

    def _extract_manufacturer_tags(self, text_blob: str) -> list[str]:
        text_blob = (text_blob or "").lower()
        found: list[str] = []
        for canonical, aliases in _MANUFACTURER_ALIASES.items():
            if any(alias in text_blob for alias in aliases):
                found.append(canonical)
        return found

    def _issue_tags_from_text(self, text_blob: str) -> list[str]:
        text_blob = (text_blob or "").lower()
        tags: list[str] = []
        if re.search(r"\bac\b|\bhvac\b|heat|cool|thermostat|air handler|condenser", text_blob):
            tags.extend(["hvac", "climate"])
        if re.search(r"leak|water|plumb|toilet|sink|shower|faucet|drain", text_blob):
            tags.extend(["plumbing", "water"])
        if re.search(r"gas|fire|smoke|unsafe|911|alarm|sparking", text_blob):
            tags.extend(["emergency", "safety"])
        if re.search(r"clean|dirty|turnover|linens|laundry|checkout|housekeeping", text_blob):
            tags.extend(["turnover", "cleaning"])
        if re.search(r"lock|door code|lockbox|can.t get in|cant get in|gate code|access", text_blob):
            tags.extend(["access", "lock"])
        if re.search(r"bike|beach chair|golf cart|rental", text_blob):
            tags.extend(["rental", "experience"])
        return sorted(set(tags))


_SERVICE = VendorIntelligenceService()


def get_vendor_intelligence_service() -> VendorIntelligenceService:
    return _SERVICE
