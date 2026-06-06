import { requestJson } from "../../api/client";

export function fetchSettingsBase() {
  return requestJson<Record<string, unknown>>("/app/api/settings");
}

export function fetchSettingsAlertRouting() {
  return requestJson<Record<string, unknown>>("/app/api/settings/alert-routing");
}

export function fetchTeamMembers() {
  return requestJson<Record<string, unknown>>("/app/api/team");
}

export function fetchTeamScopes(memberId: string) {
  return requestJson<Record<string, unknown>>(`/app/api/team/${encodeURIComponent(memberId)}/scopes`);
}

export function fetchSettingsPortfolios() {
  return requestJson<Record<string, unknown>>("/app/api/portfolios");
}

export function updateSettings(body: Record<string, unknown>) {
  return requestJson<Record<string, unknown>>("/app/api/settings", { method: "PATCH", body });
}

export function createAlertContact(body: Record<string, unknown>) {
  return requestJson<Record<string, unknown>>("/app/api/settings/alert-routing", { method: "POST", body });
}

export function updateAlertContact(contactId: string, body: Record<string, unknown>) {
  return requestJson<Record<string, unknown>>(`/app/api/settings/alert-routing/${encodeURIComponent(contactId)}`, {
    method: "PATCH",
    body,
  });
}

export function markAlertContactOOO(contactId: string, body: Record<string, unknown>) {
  return requestJson<Record<string, unknown>>(`/app/api/settings/alert-routing/${encodeURIComponent(contactId)}/ooo`, {
    method: "POST",
    body,
  });
}

export function markAlertContactAvailable(contactId: string) {
  return requestJson<Record<string, unknown>>(`/app/api/settings/alert-routing/${encodeURIComponent(contactId)}/available`, {
    method: "POST",
  });
}

export function deleteAlertContact(contactId: string) {
  return requestJson<void>(`/app/api/settings/alert-routing/${encodeURIComponent(contactId)}`, {
    method: "DELETE",
  });
}

export function inviteTeamMember(body: { name: string; email: string; role: string }) {
  return requestJson<Record<string, unknown>>("/app/api/team/invite", { method: "POST", body });
}

export function updateTeamMemberRole(memberId: string, role: string) {
  return requestJson<Record<string, unknown>>(`/app/api/team/${encodeURIComponent(memberId)}/role`, {
    method: "PATCH",
    body: { role },
  });
}

export function removeTeamMember(memberId: string) {
  return requestJson<void>(`/app/api/team/${encodeURIComponent(memberId)}`, { method: "DELETE" });
}

export function updateTeamMemberScopes(memberId: string, scopes: unknown[]) {
  return requestJson<Record<string, unknown>>(`/app/api/team/${encodeURIComponent(memberId)}/scopes`, {
    method: "PUT",
    body: { scopes },
  });
}

export function createPortfolio(body: {
  portfolio_key: string;
  display_name: string;
  description: string;
}) {
  return requestJson<Record<string, unknown>>("/app/api/portfolios", { method: "POST", body });
}

export function updatePortfolioProperties(portfolioId: string, propertyExternalIds: string[]) {
  return requestJson<Record<string, unknown>>(`/app/api/portfolios/${encodeURIComponent(portfolioId)}/properties`, {
    method: "PUT",
    body: { property_external_ids: propertyExternalIds },
  });
}
