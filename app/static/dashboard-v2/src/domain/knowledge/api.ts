import { requestJson } from "../../api/client";

export function fetchKnowledgeEntries(propertyId?: string) {
  const search = propertyId ? `?property_id=${encodeURIComponent(propertyId)}` : "";
  return requestJson<Record<string, unknown>>(`/app/api/kb${search}`);
}

export function createKnowledgeEntry(body: {
  question: string;
  answer: string;
  category: string;
  property_external_id: string;
  retry_topic: string;
}) {
  return requestJson<Record<string, unknown>>("/app/api/kb", { method: "POST", body });
}

export function updateKnowledgeEntry(
  entryId: string,
  body: { question: string; answer: string; category: string },
) {
  return requestJson<Record<string, unknown>>(`/app/api/kb/${encodeURIComponent(entryId)}`, {
    method: "PATCH",
    body,
  });
}

export function deleteKnowledgeEntry(entryId: string) {
  return requestJson<void>(`/app/api/kb/${encodeURIComponent(entryId)}`, { method: "DELETE" });
}

export function testKnowledgeQuestion(question: string) {
  return requestJson<Record<string, unknown>>("/app/api/kb/test", {
    method: "POST",
    body: { question },
  });
}

export function fetchKnowledgeGaps(resolved: boolean) {
  return requestJson<Record<string, unknown>>(`/app/api/kb-gaps?resolved=${resolved}`);
}

export function resolveKnowledgeGap(
  gapId: string,
  body: { add_to_kb: boolean; answer: string; notes: string; retry_topic: string },
) {
  return requestJson<Record<string, unknown>>(`/app/api/kb-gaps/${encodeURIComponent(gapId)}/resolve`, {
    method: "POST",
    body,
  });
}

export function dismissKnowledgeGap(gapId: string) {
  return requestJson<Record<string, unknown>>(`/app/api/kb-gaps/${encodeURIComponent(gapId)}/dismiss`, {
    method: "POST",
  });
}

export function fetchKnowledgeGuidance() {
  return requestJson<Record<string, unknown>>("/app/api/settings/ai-guidance");
}

export function saveKnowledgeGuidance(body: { guidance_text: string }) {
  return requestJson<Record<string, unknown>>("/app/api/settings/ai-guidance", {
    method: "PUT",
    body,
  });
}
