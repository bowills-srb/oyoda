import { requestJson } from "../../api/client";
import type { FilteredListPayload, PromoteResult } from "./types";

export function fetchFilteredList(params?: {
  window?: string;
  reason?: string;
  limit?: number;
}): Promise<FilteredListPayload> {
  const qs = new URLSearchParams();
  if (params?.window) qs.set("window", params.window);
  if (params?.reason) qs.set("reason", params.reason);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return requestJson<FilteredListPayload>(`/app/api/filtered${query}`);
}

export function promoteFilteredMessage(
  sourceChannel: string,
  sourceMessageId: string,
): Promise<PromoteResult> {
  return requestJson<PromoteResult>(
    `/app/api/filtered/${encodeURIComponent(sourceChannel)}/${encodeURIComponent(sourceMessageId)}/promote`,
    { method: "POST" },
  );
}
