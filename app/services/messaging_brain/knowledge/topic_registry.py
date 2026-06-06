from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class KnowledgeTopicDefinition:
    topic_id: str
    description: str
    property_schema_fields: Tuple[str, ...] = ()
    operator_policy_fields: Tuple[str, ...] = ()
    concierge_knowledge_tags: Tuple[str, ...] = ()
    keywords: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    closed_world_rule: str = "kb_only"
    negative_closure_rule: str = "none"
    negative_closure_topics: Tuple[str, ...] = ()
    gap_severity: str = "hold"
    # True → this topic should be answered at property_group (neighborhood/HOA)
    # scope, not just per-property. Used by the proactive group-gap surfacer to
    # detect "WaterSound has 12 properties but no HOA policy on file." (Gap 4)
    # Does NOT prevent property-scope overrides — the inheritance hierarchy handles
    # that. Default False; only explicitly-marked topics are expected at group scope.
    expected_at_group_scope: bool = False

    @property
    def classifier_keywords(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys([self.topic_id, *self.keywords, *self.aliases]))


_TOPICS: Tuple[KnowledgeTopicDefinition, ...] = (
    KnowledgeTopicDefinition(
        topic_id="pool_access",
        description="Whether the property has a pool that guests can use.",
        property_schema_fields=("has_pool",),
        keywords=("pool", "swimming pool", "private pool"),
        aliases=("pool_access",),
        closed_world_rule="boolean_property",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="pool_heating_capability",
        description="Whether the pool can be heated at all.",
        property_schema_fields=("has_pool", "pool_heated"),
        operator_policy_fields=("pool_heat.available",),
        concierge_knowledge_tags=("pool_heating_capability", "pool_heat"),
        keywords=("pool heated", "heated pool", "pool heat"),
        aliases=("pool_heat",),
        closed_world_rule="pool_heat_capability",
        negative_closure_rule="short_circuit_dependents",
        negative_closure_topics=("pool_heating_cost", "pool_heating_notice"),
    ),
    KnowledgeTopicDefinition(
        topic_id="pool_heating_cost",
        description="Pool heating cost, fee, or pricing details.",
        property_schema_fields=("has_pool", "pool_heated"),
        operator_policy_fields=("pool_heat.available", "pool_heat.daily_fee"),
        concierge_knowledge_tags=("pool_heating_cost", "pool_heat"),
        keywords=("pool heating cost", "pool heat cost", "heated pool cost", "pool heating fee"),
        aliases=("pool_heat_cost",),
        closed_world_rule="pool_heat_cost",
        negative_closure_rule="not_applicable_if_not_heated",
    ),
    KnowledgeTopicDefinition(
        topic_id="pool_heating_notice",
        description="Advance notice or conditions required to turn on pool heat.",
        property_schema_fields=("has_pool", "pool_heated"),
        operator_policy_fields=("pool_heat.available", "pool_heat.advance_notice_hours"),
        concierge_knowledge_tags=("pool_heating_notice", "pool_heat"),
        keywords=("pool heating notice", "pool heat notice", "pool heat in advance", "turn on pool heat"),
        aliases=("pool_heat_notice",),
        closed_world_rule="pool_heat_notice",
        negative_closure_rule="not_applicable_if_not_heated",
    ),
    KnowledgeTopicDefinition(
        topic_id="hot_tub_access",
        description="Whether the property has a hot tub guests can use.",
        property_schema_fields=("has_hot_tub",),
        concierge_knowledge_tags=("hot_tub_access", "hot_tub"),
        keywords=("hot tub", "jacuzzi", "spa"),
        aliases=("hot_tub",),
        closed_world_rule="boolean_property",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="beach_access",
        description="How the beach is accessed from the property.",
        property_schema_fields=("beach_access_type",),
        concierge_knowledge_tags=("beach_access",),
        keywords=("beach access", "walk to beach", "private beach", "public access"),
        aliases=("beach_access",),
        closed_world_rule="enum_presence",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="beach_gear",
        description="What beach gear is provided at the property.",
        concierge_knowledge_tags=("beach_gear",),
        keywords=("beach chairs", "umbrella", "cooler", "beach gear"),
        aliases=("amenities",),
        closed_world_rule="kb_or_evidence",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="golf_cart",
        description="Whether a golf cart is included and available for guests.",
        concierge_knowledge_tags=("golf_cart",),
        keywords=("golf cart",),
        aliases=("amenities",),
        closed_world_rule="kb_or_evidence",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="parking",
        description="Where guests can park and any parking restrictions.",
        property_schema_fields=("parking_summary",),
        concierge_knowledge_tags=("parking",),
        keywords=("parking", "park", "garage", "driveway"),
        aliases=("parking",),
        closed_world_rule="text_presence",
        negative_closure_rule="none",
        expected_at_group_scope=True,  # HOA/community parking rules apply neighborhood-wide
    ),
    KnowledgeTopicDefinition(
        topic_id="sleeping_arrangement",
        description="Bedroom layout, bed setup, and sleeping arrangement details.",
        property_schema_fields=("bedrooms", "max_guests"),
        concierge_knowledge_tags=("sleeping_arrangement", "bedrooms", "beds"),
        keywords=("bedrooms", "beds", "sleeping arrangement", "sleep", "bunk room"),
        aliases=("sleeping_arrangement",),
        closed_world_rule="sleeping_arrangement",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="max_occupancy",
        description="Maximum number of guests the property can host.",
        property_schema_fields=("max_guests", "bedrooms"),
        concierge_knowledge_tags=("max_occupancy", "max_guests"),
        keywords=("how many guests", "max guests", "occupancy", "sleep"),
        aliases=("group_or_event",),
        closed_world_rule="max_occupancy",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="pet_policy",
        description="Whether pets are allowed at the property.",
        property_schema_fields=("pet_friendly",),
        operator_policy_fields=("pet_policy",),
        concierge_knowledge_tags=("pet_policy",),
        keywords=("pet", "dog", "cat", "service animal"),
        aliases=("pet_policy",),
        closed_world_rule="pet_policy",
        negative_closure_rule="short_circuit_dependents",
        negative_closure_topics=("pet_fee",),
    ),
    KnowledgeTopicDefinition(
        topic_id="pet_fee",
        description="Pet fee or extra pet charges.",
        property_schema_fields=("pet_friendly",),
        operator_policy_fields=("pet_policy", "pet_fee"),
        concierge_knowledge_tags=("pet_fee",),
        keywords=("pet fee", "dog fee", "pet charge"),
        aliases=("pet_policy",),
        closed_world_rule="pet_fee",
        negative_closure_rule="not_applicable_if_pets_denied",
    ),
    KnowledgeTopicDefinition(
        topic_id="check_in_process",
        description="How check-in works and when check-in starts.",
        property_schema_fields=("check_in_time",),
        operator_policy_fields=("check_in_time",),
        concierge_knowledge_tags=("check_in_process", "check_in"),
        keywords=("check in", "check-in", "arrival instructions", "door code"),
        aliases=("check_in_process",),
        closed_world_rule="check_in_process",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="early_check_in",
        description="Whether early check-in is available and under what terms.",
        operator_policy_fields=("early_checkin.allowed", "early_checkin.earliest", "early_checkin_fee"),
        concierge_knowledge_tags=("early_check_in",),
        keywords=("early check in", "early arrival", "arrive early"),
        aliases=("check_in_process",),
        closed_world_rule="early_check_in",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="late_check_out",
        description="Whether late checkout is available and under what terms.",
        operator_policy_fields=("late_checkout.allowed", "late_checkout.max_time", "late_checkout_fee"),
        concierge_knowledge_tags=("late_check_out",),
        keywords=("late check out", "late checkout", "stay later"),
        aliases=("check_in_process",),
        closed_world_rule="late_check_out",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="cleaning_fee",
        description="Cleaning fee amount or whether one applies.",
        property_schema_fields=("cleaning_fee",),
        concierge_knowledge_tags=("cleaning_fee",),
        keywords=("cleaning fee", "cleaning charge"),
        aliases=("pricing",),
        closed_world_rule="numeric_property",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="cancellation_policy",
        description="Cancellation windows, refunds, and cancellation terms.",
        operator_policy_fields=(
            "cancellation.full_refund_days",
            "cancellation.partial_refund_days",
            "cancellation.partial_refund_percent",
        ),
        concierge_knowledge_tags=("cancellation_policy",),
        keywords=("cancellation", "cancel", "refund"),
        aliases=("pricing",),
        closed_world_rule="cancellation_policy",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="payment_schedule",
        description="When payments are due and how much is due at booking versus later.",
        concierge_knowledge_tags=("payment_schedule",),
        keywords=("payment schedule", "when do i pay", "deposit due", "pay the balance"),
        aliases=("pricing",),
        closed_world_rule="kb_only",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="deposit_policy",
        description="Security deposit, hold, or damage waiver details.",
        concierge_knowledge_tags=("deposit_policy",),
        keywords=("security deposit", "damage deposit", "hold on card", "damage waiver"),
        aliases=("pricing",),
        closed_world_rule="kb_only",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="local_area",
        description="Neighborhood, surrounding area, and local-area orientation.",
        property_schema_fields=("property_summary", "description", "community_name"),
        concierge_knowledge_tags=("local_area", "neighborhood"),
        keywords=("nearby", "neighborhood", "walk to", "area", "restaurants nearby"),
        aliases=("local_area", "neighborhood"),
        closed_world_rule="text_presence",
        negative_closure_rule="none",
        gap_severity="review",
        expected_at_group_scope=True,  # community orientation belongs at neighborhood scope
    ),
    KnowledgeTopicDefinition(
        topic_id="accessibility",
        description="Accessibility and mobility-related accommodations.",
        property_schema_fields=("description",),
        concierge_knowledge_tags=("accessibility",),
        keywords=("accessible", "wheelchair", "stairs", "elevator"),
        aliases=("accessibility",),
        closed_world_rule="kb_or_evidence",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="wifi_access",
        description="Wifi network name, password, and connectivity information.",
        concierge_knowledge_tags=("wifi_access", "wifi", "internet"),
        keywords=("wifi", "wi-fi", "wireless", "internet", "network", "password", "ssid"),
        aliases=("wifi_access", "internet"),
        closed_world_rule="text_presence",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="emergency_contacts",
        description="Emergency phone numbers, property manager contact, and after-hours support.",
        concierge_knowledge_tags=("emergency_contacts", "contact_info", "emergency"),
        keywords=("emergency", "911", "emergency contact", "property manager phone", "after hours", "urgent contact"),
        aliases=("emergency_contacts", "contact_info"),
        closed_world_rule="text_presence",
        negative_closure_rule="none",
    ),
    KnowledgeTopicDefinition(
        topic_id="trash_disposal",
        description="Trash pickup schedule, recycling instructions, and bin location.",
        concierge_knowledge_tags=("trash_disposal", "trash", "recycling"),
        keywords=("trash", "garbage", "recycling", "pickup day", "bin location", "dumpster"),
        aliases=("trash_disposal",),
        closed_world_rule="text_presence",
        negative_closure_rule="none",
        expected_at_group_scope=True,  # neighborhood-wide pickup schedules recur HOA-wide
    ),
    KnowledgeTopicDefinition(
        topic_id="quiet_hours",
        description="Noise restrictions and quiet-hours policy.",
        concierge_knowledge_tags=("quiet_hours", "noise_policy"),
        keywords=("quiet hours", "noise", "music", "loud", "noise ordinance", "quiet time"),
        aliases=("quiet_hours", "noise_policy"),
        closed_world_rule="text_presence",
        negative_closure_rule="none",
        expected_at_group_scope=True,  # HOA quiet-hours ordinances apply across the community
    ),
    KnowledgeTopicDefinition(
        topic_id="smoking_policy",
        description="Whether smoking is allowed at the property, including any outdoor restrictions.",
        concierge_knowledge_tags=("smoking_policy", "smoking"),
        keywords=("smoking", "smoke", "cigarette", "vape", "vaping", "non-smoking", "no smoking"),
        aliases=("smoking_policy",),
        closed_world_rule="kb_only",
        negative_closure_rule="none",
    ),
    # ── Group-scope / neighborhood / HOA topics ──────────────────────────────
    # These topics are primarily meaningful at property_group (neighborhood/HOA)
    # scope. They answer community-level questions that apply to every member
    # property, not just one unit. expected_at_group_scope=True drives the
    # proactive gap surfacer (Gap 4): if a group has members but no entry for
    # these topics, the operator is prompted to fill it once → all inherit.
    KnowledgeTopicDefinition(
        topic_id="hoa_rules",
        description="HOA policies governing the community: rules guests must follow, "
                    "restrictions on vehicles, noise, parties, etc.",
        concierge_knowledge_tags=("hoa_rules", "hoa", "community_rules"),
        keywords=("hoa", "homeowner association", "community rules", "hoa rules",
                  "association rules", "condo rules", "community policy"),
        aliases=("hoa_rules",),
        closed_world_rule="kb_only",
        negative_closure_rule="none",
        gap_severity="review",
        expected_at_group_scope=True,
    ),
    KnowledgeTopicDefinition(
        topic_id="required_vendors",
        description="Vendors that must or should be used within the community — e.g. "
                    "HOA-approved golf-cart rental companies with contact info. The answer "
                    "should include vendor names and phone numbers, not just 'must use HOA-approved'.",
        concierge_knowledge_tags=("required_vendors", "approved_vendors", "golf_cart_rental"),
        keywords=("approved vendor", "required vendor", "golf cart rental", "cart rental",
                  "hoa approved vendor", "approved company", "who to call"),
        aliases=("required_vendors",),
        closed_world_rule="kb_only",
        negative_closure_rule="none",
        gap_severity="review",
        expected_at_group_scope=True,
    ),
    KnowledgeTopicDefinition(
        topic_id="gate_code",
        description="Gate codes and access procedures for the community — entrance gates, "
                    "amenity access codes, call-box instructions.",
        concierge_knowledge_tags=("gate_code", "community_access", "access_code"),
        keywords=("gate code", "gate", "access code", "call box", "community gate",
                  "entrance gate", "security gate", "amenity code"),
        aliases=("gate_code", "community_access"),
        closed_world_rule="text_presence",
        negative_closure_rule="none",
        gap_severity="hold",
        expected_at_group_scope=True,
    ),
    KnowledgeTopicDefinition(
        topic_id="community_amenities",
        description="Shared community amenities: pools, beach access points, tennis courts, "
                    "fitness centers, docks — anything shared across the neighborhood.",
        concierge_knowledge_tags=("community_amenities", "shared_amenities", "community_pool"),
        keywords=("community pool", "shared pool", "community amenities", "community beach access",
                  "tennis court", "fitness center", "community dock", "shared facilities"),
        aliases=("community_amenities",),
        closed_world_rule="kb_or_evidence",
        negative_closure_rule="none",
        gap_severity="review",
        expected_at_group_scope=True,
    ),
)


TOPIC_REGISTRY: Dict[str, KnowledgeTopicDefinition] = {topic.topic_id: topic for topic in _TOPICS}

LEGACY_TOPIC_ALIAS_MAP: Dict[str, Tuple[str, ...]] = {
    "amenities": (
        "pool_access",
        "pool_heating_capability",
        "hot_tub_access",
        "beach_gear",
        "golf_cart",
    ),
    "beach_access": ("beach_access",),
    "sleeping_arrangement": ("sleeping_arrangement", "max_occupancy"),
    "pet_policy": ("pet_policy", "pet_fee"),
    "parking": ("parking",),
    "check_in_process": ("check_in_process", "early_check_in", "late_check_out"),
    "group_or_event": ("max_occupancy",),
    "accessibility": ("accessibility",),
    "local_area": ("local_area",),
    "pricing": ("cleaning_fee", "cancellation_policy", "payment_schedule", "deposit_policy"),
}


def iter_knowledge_topics() -> Iterable[KnowledgeTopicDefinition]:
    return _TOPICS


def get_group_expected_topics() -> Tuple[KnowledgeTopicDefinition, ...]:
    """Return topics expected at property_group (neighborhood/HOA) scope.

    Used by the proactive group-gap surfacer (Gap 4) to detect neighborhoods
    that are missing community-level knowledge (HOA rules, required vendors,
    gate codes, etc.). The returned set is the single source of truth for
    "what should a property_group have on file."
    """
    return tuple(t for t in _TOPICS if t.expected_at_group_scope)


def get_knowledge_topic(topic_id: str) -> KnowledgeTopicDefinition | None:
    return TOPIC_REGISTRY.get(topic_id)


def expand_legacy_topics(topics: List[str]) -> List[str]:
    expanded: List[str] = []
    for topic in topics:
        normalized = (topic or "").strip()
        if not normalized:
            continue
        mapped = LEGACY_TOPIC_ALIAS_MAP.get(normalized)
        if mapped:
            expanded.extend(mapped)
            continue
        if normalized in TOPIC_REGISTRY:
            expanded.append(normalized)
    return list(dict.fromkeys(expanded))


def topic_prompt_catalog() -> str:
    lines = []
    for topic in _TOPICS:
        lines.append(f"- {topic.topic_id}: {topic.description}")
    return "\n".join(lines)
