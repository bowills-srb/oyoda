import { queryOptions } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import {
  fetchKnowledgeEntries,
  fetchKnowledgeGaps,
  fetchKnowledgeGuidance,
} from "./api";
import {
  normalizeKnowledgeEntries,
  normalizeKnowledgeGaps,
  normalizeKnowledgeGuidance,
} from "./normalize";

export function knowledgeEntriesQueryOptions(property: string) {
  return queryOptions({
    queryKey: queryKeys.knowledge.entries(property),
    queryFn: async () => normalizeKnowledgeEntries(await fetchKnowledgeEntries(property || undefined)),
    staleTime: 30_000,
  });
}

export function knowledgeGapsQueryOptions(resolved: boolean) {
  return queryOptions({
    queryKey: queryKeys.knowledge.gaps(resolved),
    queryFn: async () => normalizeKnowledgeGaps(await fetchKnowledgeGaps(resolved)),
    staleTime: 30_000,
  });
}

export function knowledgeGuidanceQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.knowledge.guidance(),
    queryFn: async () => normalizeKnowledgeGuidance(await fetchKnowledgeGuidance()),
    staleTime: 30_000,
  });
}
