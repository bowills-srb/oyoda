import type {
  PortfolioOption,
  PropertyAsset,
  PropertyGap,
  PropertyKbEntry,
  PropertyRow,
} from "../../routes/Properties/types";

import type { IdentityReportProperty } from "./types";

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

function safeNumber(value: unknown, fallback = 0): number {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function safeString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : value == null ? fallback : String(value);
}

export function mergeProperties(
  autonomyPayload: Record<string, unknown>,
  identityPayload: Record<string, unknown>,
): PropertyRow[] {
  const identityByCode = new Map<string, IdentityReportProperty>();
  for (const item of safeArray<IdentityReportProperty>(identityPayload.properties)) {
    const code = safeString(item.property_code).trim();
    if (code) identityByCode.set(code, item);
  }

  const rawProperties = safeArray<Record<string, unknown>>(autonomyPayload.properties);
  return rawProperties.map((raw): PropertyRow => {
    const propertyCode = safeString(raw.property_code || raw.propertyCode).trim();
    const externalId = safeString(raw.external_id || raw.externalId).trim();
    const identity = identityByCode.get(propertyCode) || {};
    const rawAutonomy =
      raw.autonomy && typeof raw.autonomy === "object" ? (raw.autonomy as Record<string, unknown>) : {};
    const autonomy =
      ("all" in rawAutonomy && rawAutonomy.all && typeof rawAutonomy.all === "object"
        ? (rawAutonomy.all as Record<string, unknown>)
        : undefined) || rawAutonomy;

    return {
      id: safeString(raw.id || raw.property_id),
      propertyCode,
      externalId,
      propertyName: safeString(
        raw.property_name || raw.propertyName || identity.display_name || identity.marketing_name,
      ),
      displayName: safeString(identity.display_name || raw.display_name),
      marketingName: safeString(identity.marketing_name || raw.marketing_name),
      addressStreet: safeString(raw.address_street || raw.addressStreet),
      addressCity: safeString(raw.address_city || raw.addressCity),
      addressState: safeString(raw.address_state || raw.addressState),
      community: safeString(raw.community),
      dataSource: safeString(raw.data_source || raw.dataSource),
      bedrooms: raw.bedrooms == null ? null : safeNumber(raw.bedrooms),
      bathrooms: raw.bathrooms == null ? null : safeNumber(raw.bathrooms),
      sleeps: raw.sleeps == null ? null : safeNumber(raw.sleeps),
      hasPool: Boolean(raw.has_pool ?? raw.hasPool),
      hasHotTub: Boolean(raw.has_hot_tub ?? raw.hasHotTub),
      petsAllowed: Boolean(raw.pets_allowed ?? raw.petsAllowed),
      approvalMode: safeString(autonomy.approval_mode || autonomy.approvalMode || raw.approval_mode, "required"),
      minConfidenceForAuto: safeNumber(
        autonomy.min_confidence_for_auto ?? autonomy.minConfidenceForAuto ?? raw.min_confidence_for_auto,
        0.95,
      ),
      pmsPropertyIds: safeArray(identity.pms_property_ids).map(String),
      pmsUnitCodes: safeArray(identity.pms_unit_codes).map(String),
      otaRefs: identity.ota_refs && typeof identity.ota_refs === "object" ? identity.ota_refs : {},
      aliases: safeArray(identity.aliases).map(String),
      knowledgeCount: safeNumber(identity.knowledge_count),
      assetCount: safeNumber(identity.asset_count),
      reviewStatusPending: safeNumber(identity.review_status?.pending),
      profileUpdatedAt: identity.profile_updated_at || null,
      knowledgeRef: propertyCode || externalId,
    };
  });
}

export function normalizePropertyKbEntries(payload: Record<string, unknown>): PropertyKbEntry[] {
  return safeArray<Record<string, unknown>>(payload.entries).map((entry) => ({
    id: safeString(entry.id),
    question: safeString(entry.question),
    answer: safeString(entry.answer),
    category: safeString(entry.category, "General"),
    confidence: safeNumber(entry.confidence, 0.9),
    usageCount: safeNumber(entry.usage_count),
    updatedAt: (entry.updated_at as string | null | undefined) || null,
  }));
}

export function normalizePropertyAssets(payload: Record<string, unknown>): PropertyAsset[] {
  return safeArray<Record<string, unknown>>(payload.assets).map((asset) => ({
    assetId: safeString(asset.asset_id || asset.id),
    assetType: safeString(asset.asset_type),
    assetName: safeString(asset.asset_name),
    manufacturer: safeString(asset.manufacturer),
    modelNumber: safeString(asset.model_number),
    serialNumber: safeString(asset.serial_number),
    status: safeString(asset.status, "active"),
    warrantyEndDate: (asset.warranty_end_date as string | null | undefined) || null,
    installDate: (asset.install_date as string | null | undefined) || null,
    lastServiceAt: (asset.last_service_at as string | null | undefined) || null,
    notes: safeString(asset.notes),
    updatedAt: (asset.updated_at as string | null | undefined) || null,
  }));
}

export function normalizePropertyGaps(payload: Record<string, unknown>): PropertyGap[] {
  return safeArray<Record<string, unknown>>(payload.gaps).map((gap) => ({
    id: safeString(gap.gap_id || gap.id),
    question: safeString(gap.question),
    category: safeString(gap.category, "General"),
    categorySlug: safeString(gap.category_slug || gap.detected_intent, "general"),
    property: safeString(gap.property),
    missingTopics: safeArray(gap.missing_topics).map(String),
    askCount: safeNumber(gap.ask_count, 1),
    reason: safeString(gap.reason),
    createdAt: (gap.created_at as string | null | undefined) || null,
    lastAskedAt: (gap.last_asked_at as string | null | undefined) || (gap.created_at as string | null | undefined) || null,
  }));
}

export function normalizePortfolios(payload: Record<string, unknown>): PortfolioOption[] {
  return safeArray<Record<string, unknown>>(payload.portfolios).map((portfolio) => ({
    portfolioKey: safeString(portfolio.portfolio_key),
    displayName: safeString(portfolio.display_name || portfolio.portfolio_key, "Portfolio"),
    propertyCount: safeNumber(portfolio.property_count),
    propertyExternalIds: safeArray(portfolio.property_external_ids).map(String),
  }));
}
