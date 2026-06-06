import { requestJson } from "../../api/client";

import { fetchAutonomy, saveAutonomy as saveAutonomyRequest } from "../autonomy/api";
import { fetchSession } from "../auth/api";
import type { AutonomyPayload } from "../autonomy/types";
import type { SessionPayload } from "../auth/types";

import type {
  BindPropertyInput,
  BindPropertyResult,
  BootstrapPayload,
  MessageFeed,
  PropertySuggestionResponse,
} from "./types";
import { normalizePreBookingMessageFeed } from "./normalize";

export function fetchPreBookingSession(): Promise<SessionPayload> {
  return fetchSession();
}

export function fetchPreBookingAutonomy(): Promise<AutonomyPayload> {
  return fetchAutonomy();
}

export function fetchPreBookingMessageFeed(): Promise<MessageFeed> {
  return requestJson<Record<string, unknown>>("/app/api/messages?stage=pre_booking").then(normalizePreBookingMessageFeed);
}

export function fetchPreBookingBootstrap() {
  return requestJson<BootstrapPayload>("/app/api/v2/prebooking/bootstrap");
}

export function approveInquiry(id: string) {
  return requestJson<void>(`/app/api/inquiries/${encodeURIComponent(id)}/approve`, { method: "POST" });
}

export function rejectInquiry(id: string) {
  return requestJson<void>(`/app/api/inquiries/${encodeURIComponent(id)}/reject`, { method: "POST" });
}

export function editInquiry(id: string, body: { reply_text: string }) {
  return requestJson<void>(`/app/api/inquiries/${encodeURIComponent(id)}/edit`, { method: "POST", body });
}

export function bindInquiryProperty(id: string, body: BindPropertyInput) {
  return requestJson<BindPropertyResult>(`/app/api/inquiries/${encodeURIComponent(id)}/bind-property`, {
    method: "POST",
    body,
  });
}

export function suggestPropertyLinks(query: string, limit = 6) {
  return requestJson<PropertySuggestionResponse>(
    `/app/api/property-links/suggest?query=${encodeURIComponent(query)}&limit=${encodeURIComponent(limit)}`,
  );
}

export function savePreBookingAutonomy(tenant: { auto_enabled: boolean; confidence_threshold: number }) {
  return saveAutonomyRequest(tenant);
}
