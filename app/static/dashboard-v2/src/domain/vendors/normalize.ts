import type { Vendor, VendorCategory } from "./types";

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

export function normalizeVendorCategories(payload: Record<string, unknown>): VendorCategory[] {
  return safeArray<Record<string, unknown>>(payload.categories).map((category) => ({
    id: safeString(category.category_id || category.id),
    slug: safeString(category.slug),
    displayName: safeString(category.display_name, "Category"),
    icon: safeString(category.icon, ""),
    sortOrder: safeNumber(category.sort_order),
    vendorCount: safeNumber(category.vendor_count),
    workflowGroup: safeString(category.workflow_group, "experience"),
  }));
}

export function normalizeVendors(payload: Record<string, unknown>): Vendor[] {
  return safeArray<Record<string, unknown>>(payload.vendors).map((vendor) => {
    const operationalMetadata =
      vendor.operational_metadata && typeof vendor.operational_metadata === "object"
        ? (vendor.operational_metadata as Record<string, unknown>)
        : {};

    return {
      id: safeString(vendor.vendor_id || vendor.id),
      name: safeString(vendor.name),
      categorySlug: safeString(vendor.category_slug),
      phone: safeString(vendor.phone),
      website: safeString(vendor.website),
      aiScript: safeString(vendor.ai_script),
      internalNotes: safeString(vendor.internal_notes),
      priority: safeNumber(vendor.priority, 1),
      applyScope: safeString(vendor.apply_scope, "all"),
      propertyIds: safeArray(vendor.property_ids).map(String),
      active: vendor.active !== false,
      referralCount: safeNumber(vendor.referral_count),
      lastReferredAt: (vendor.last_referred_at as string | null | undefined) || null,
      workflowGroup: safeString(vendor.workflow_group, "experience"),
      operationalMetadata: {
        manufacturerTags: safeArray(operationalMetadata.manufacturer_tags).map(String),
        excludedManufacturerTags: safeArray(operationalMetadata.excluded_manufacturer_tags).map(String),
        warrantyProviderTags: safeArray(operationalMetadata.warranty_provider_tags).map(String),
        supportedIssueTags: safeArray(operationalMetadata.supported_issue_tags).map(String),
        preferredPropertyCodes: safeArray(operationalMetadata.preferred_property_codes).map(String),
        warrantyCapable: Boolean(operationalMetadata.warranty_capable),
        warrantyOnly: Boolean(operationalMetadata.warranty_only),
        emergencyCapable: Boolean(operationalMetadata.emergency_capable),
        emergencyOverrideOnly: Boolean(operationalMetadata.emergency_override_only),
        afterHoursAvailable: Boolean(operationalMetadata.after_hours_available),
        backupRank: safeNumber(operationalMetadata.backup_rank),
        responseSlaMinutes: safeNumber(operationalMetadata.response_sla_minutes),
        approvalMode: safeString(operationalMetadata.approval_mode, "standard"),
        costTier: safeString(operationalMetadata.cost_tier, "standard"),
      },
    };
  });
}
