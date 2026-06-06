import { normalizeAlertRouting, normalizeSettings, normalizeTeamMembers } from "../../adapters/index.js";

import type { SettingsPortfolio, SettingsPropertyOption, SettingsTeamScope } from "./types";

function safeArray<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function normalizeSettingsPropertyOptions(
  autonomyPayload: Record<string, unknown>,
  identityPayload: Record<string, unknown>,
): SettingsPropertyOption[] {
  const identityByCode = new Map<string, Record<string, unknown>>();
  for (const item of safeArray<Record<string, unknown>>(identityPayload.properties)) {
    const code = String(item.property_code || "").trim();
    if (code) identityByCode.set(code, item);
  }
  const rows = safeArray<Record<string, unknown>>(autonomyPayload.properties);
  const options = rows
    .map((raw) => {
      const propertyCode = String(raw.property_code || raw.propertyCode || "").trim();
      const externalId = String(raw.external_id || raw.externalId || "").trim();
      const identity = identityByCode.get(propertyCode) || {};
      const label = String(
        raw.property_name ||
          raw.propertyName ||
          identity.display_name ||
          identity.marketing_name ||
          propertyCode ||
          externalId,
      ).trim();
      if (!propertyCode && !externalId) return null;
      return { propertyCode, externalId, label };
    })
    .filter(Boolean) as SettingsPropertyOption[];
  const deduped = new Map<string, SettingsPropertyOption>();
  for (const option of options) {
    const key = `${option.propertyCode}::${option.externalId}`;
    if (!deduped.has(key)) deduped.set(key, option);
  }
  return Array.from(deduped.values()).sort((a, b) => a.label.localeCompare(b.label));
}

export function normalizeSettingsScopes(payload: Record<string, unknown>): SettingsTeamScope[] {
  const scopes = safeArray<Record<string, unknown>>(payload.scopes);
  return scopes.map((scope) => ({
    scope_id: String(scope.scope_id || ""),
    scope_type: String(scope.scope_type || "property") as SettingsTeamScope["scope_type"],
    portfolio_id: String(scope.portfolio_id || ""),
    property_external_id: String(scope.property_external_id || ""),
    can_view: scope.can_view !== false,
    can_assign: Boolean(scope.can_assign),
    can_manage_vendors: Boolean(scope.can_manage_vendors),
    can_manage_settings: Boolean(scope.can_manage_settings),
  }));
}

export function normalizeSettingsPortfolios(payload: Record<string, unknown>): SettingsPortfolio[] {
  const portfolios = safeArray<Record<string, unknown>>(payload.portfolios);
  return portfolios.map((portfolio) => ({
    id: String(portfolio.portfolio_id || ""),
    portfolioKey: String(portfolio.portfolio_key || ""),
    displayName: String(portfolio.display_name || portfolio.portfolio_key || "Portfolio"),
    description: String(portfolio.description || ""),
    active: portfolio.active !== false,
    propertyCount: Number(portfolio.property_count || 0),
    propertyExternalIds: safeArray(portfolio.property_external_ids).map(String),
  }));
}

export { normalizeAlertRouting, normalizeSettings, normalizeTeamMembers };
