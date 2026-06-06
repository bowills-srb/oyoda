import { requestJson } from "../../api/client";
import type {
  AssignInput,
  CoordinationInput,
  DispatchVendorInput,
  EscalationsPayload,
  ResolveInput,
} from "./types";
import { normalizeEscalationsPayload } from "./normalize";

export function fetchEscalations(params?: { status?: string; limit?: number }): Promise<EscalationsPayload> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  const query = qs.toString() ? `?${qs.toString()}` : "";
  return requestJson<unknown>(`/app/api/escalations${query}`).then(normalizeEscalationsPayload);
}

export function assignEscalation(ticketId: string, body: AssignInput): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(`/app/api/escalations/${encodeURIComponent(ticketId)}/assign`, {
    method: "POST",
    body,
  });
}

export function resolveEscalation(ticketId: string, body: ResolveInput): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(`/app/api/escalations/${encodeURIComponent(ticketId)}/resolve`, {
    method: "POST",
    body,
  });
}

export function dispatchVendor(ticketId: string, body: DispatchVendorInput): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(`/app/api/escalations/${encodeURIComponent(ticketId)}/dispatch-vendor`, {
    method: "POST",
    body,
  });
}

export function saveCoordination(ticketId: string, body: CoordinationInput): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(`/app/api/escalations/${encodeURIComponent(ticketId)}/coordination`, {
    method: "POST",
    body,
  });
}
