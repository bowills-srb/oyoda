import { requestJson } from "../../api/client";

export function fetchPropertiesAutonomy() {
  return requestJson<Record<string, unknown>>("/app/api/properties/autonomy");
}

export function fetchPropertyIdentityReport() {
  return requestJson<Record<string, unknown>>("/app/api/properties/identity-report");
}

export function fetchPortfolios() {
  return requestJson<Record<string, unknown>>("/app/api/portfolios");
}

export function fetchKbGaps(resolved = false) {
  return requestJson<Record<string, unknown>>(`/app/api/kb-gaps?resolved=${resolved}`);
}

export function fetchPropertyKb(knowledgeRef: string) {
  return requestJson<Record<string, unknown>>(`/app/api/kb?property_id=${encodeURIComponent(knowledgeRef)}`);
}

export function fetchPropertyAssets(propertyCode: string) {
  return requestJson<Record<string, unknown>>(`/app/api/properties/${encodeURIComponent(propertyCode)}/assets`);
}

export function resolveKbGap(gapId: string, body: { notes: string; retry_topic: string }) {
  return requestJson<Record<string, unknown>>(`/app/api/kb-gaps/${encodeURIComponent(gapId)}/resolve`, {
    method: "POST",
    body,
  });
}
