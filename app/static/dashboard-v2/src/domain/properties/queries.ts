import { queryOptions } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import {
  fetchKbGaps,
  fetchPortfolios,
  fetchPropertiesAutonomy,
  fetchPropertyAssets,
  fetchPropertyIdentityReport,
  fetchPropertyKb,
} from "./api";
import {
  mergeProperties,
  normalizePortfolios,
  normalizePropertyAssets,
  normalizePropertyGaps,
  normalizePropertyKbEntries,
} from "./normalize";

export function propertiesRosterQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.properties.roster(),
    queryFn: async () => {
      const [autonomyPayload, identityPayload] = await Promise.all([
        fetchPropertiesAutonomy(),
        fetchPropertyIdentityReport(),
      ]);
      return mergeProperties(autonomyPayload, identityPayload);
    },
    staleTime: 30_000,
  });
}

export function propertiesPortfoliosQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.properties.portfolios(),
    queryFn: async () => normalizePortfolios(await fetchPortfolios()),
    staleTime: 30_000,
  });
}

export function propertiesGapsQueryOptions(resolved = false) {
  return queryOptions({
    queryKey: queryKeys.properties.gaps(resolved),
    queryFn: async () => normalizePropertyGaps(await fetchKbGaps(resolved)),
    staleTime: 30_000,
  });
}

export function propertyKbQueryOptions(knowledgeRef: string) {
  return queryOptions({
    queryKey: queryKeys.properties.kb(knowledgeRef),
    queryFn: async () => normalizePropertyKbEntries(await fetchPropertyKb(knowledgeRef)),
    staleTime: 30_000,
  });
}

export function propertyAssetsQueryOptions(propertyCode: string) {
  return queryOptions({
    queryKey: queryKeys.properties.assets(propertyCode),
    queryFn: async () => normalizePropertyAssets(await fetchPropertyAssets(propertyCode)),
    staleTime: 30_000,
  });
}
