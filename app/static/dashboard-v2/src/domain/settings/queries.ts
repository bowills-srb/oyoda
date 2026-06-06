import { queryOptions } from "@tanstack/react-query";

import { fetchAutonomy } from "../autonomy/api";
import { fetchPropertyIdentityReport, fetchPropertiesAutonomy } from "../properties/api";
import { queryKeys } from "../../lib/query/queryKeys";

import {
  fetchSettingsAlertRouting,
  fetchSettingsBase,
  fetchSettingsPortfolios,
  fetchTeamMembers,
  fetchTeamScopes,
} from "./api";
import {
  normalizeAlertRouting,
  normalizeSettings,
  normalizeSettingsPortfolios,
  normalizeSettingsPropertyOptions,
  normalizeSettingsScopes,
  normalizeTeamMembers,
} from "./normalize";

export function settingsBaseQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.settings.base(),
    queryFn: async () => normalizeSettings(await fetchSettingsBase()),
    staleTime: 30_000,
  });
}

export function settingsAutonomyQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.autonomy.current(),
    queryFn: fetchAutonomy,
    staleTime: 30_000,
  });
}

export function settingsAlertRoutingQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.settings.alertRouting(),
    queryFn: async () => {
      const payload = normalizeAlertRouting(await fetchSettingsAlertRouting());
      return {
        contacts: payload.contacts,
        coverage: payload.coverage,
        alertTypes: payload.alertTypes || [],
        properties: (payload.properties || []).map((property: Record<string, unknown>) => ({
          propertyCode: String(property.propertyCode || property.property_code || ""),
          externalId: String(property.propertyId || property.property_id || ""),
          label: String(property.propertyName || property.property_name || property.propertyCode || "Property"),
        })),
      };
    },
    staleTime: 30_000,
  });
}

export function settingsTeamBundleQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.settings.team(),
    queryFn: async () => {
      const [teamPayload, portfolioPayload, autonomyPayload, identityPayload] = await Promise.all([
        fetchTeamMembers(),
        fetchSettingsPortfolios(),
        fetchPropertiesAutonomy(),
        fetchPropertyIdentityReport(),
      ]);
      const members = normalizeTeamMembers(teamPayload).members;
      const scopeEntries = await Promise.all(
        members.map(async (member: { id: string }) => {
          try {
            const scopesPayload = await fetchTeamScopes(member.id);
            return [member.id, normalizeSettingsScopes(scopesPayload)] as const;
          } catch {
            return [member.id, []] as const;
          }
        }),
      );
      return {
        members,
        memberScopes: Object.fromEntries(scopeEntries),
        portfolios: normalizeSettingsPortfolios(portfolioPayload),
        propertyOptions: normalizeSettingsPropertyOptions(autonomyPayload, identityPayload),
      };
    },
    staleTime: 30_000,
  });
}

export function settingsPortfoliosBundleQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.settings.portfolios(),
    queryFn: async () => {
      const [portfolioPayload, autonomyPayload, identityPayload] = await Promise.all([
        fetchSettingsPortfolios(),
        fetchPropertiesAutonomy(),
        fetchPropertyIdentityReport(),
      ]);
      return {
        portfolios: normalizeSettingsPortfolios(portfolioPayload),
        propertyOptions: normalizeSettingsPropertyOptions(autonomyPayload, identityPayload),
      };
    },
    staleTime: 30_000,
  });
}
