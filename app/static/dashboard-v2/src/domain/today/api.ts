import { requestJson } from "../../api/client";

export function fetchTodaySessions(params: { include_archived: boolean; limit: number }) {
  const qs = new URLSearchParams();
  qs.set("include_archived", String(params.include_archived));
  qs.set("limit", String(params.limit));
  return requestJson<Record<string, unknown>>(`/app/api/sessions?${qs.toString()}`);
}

export function fetchTodayEscalations() {
  return requestJson<Record<string, unknown>>("/app/api/escalations");
}

export function fetchTodaySessionDetail(sessionId: string) {
  return requestJson<Record<string, unknown>>(`/app/api/sessions/${encodeURIComponent(sessionId)}`);
}

export function fetchTodaySessionWorkOrders(sessionId: string) {
  return requestJson<Record<string, unknown>>(`/app/api/sessions/${encodeURIComponent(sessionId)}/work-orders`);
}

export function fetchTodaySessionActions(sessionId: string) {
  return requestJson<Record<string, unknown>>(`/app/api/sessions/${encodeURIComponent(sessionId)}/actions`);
}

export function executeTodaySessionAction(sessionId: string, actionType: string) {
  return requestJson(`/app/api/sessions/${encodeURIComponent(sessionId)}/actions/${encodeURIComponent(actionType)}/execute`, {
    method: "POST",
  });
}

export function sendTodaySessionUpdate(sessionId: string, body: { message_text: string }) {
  return requestJson(`/app/api/sessions/${encodeURIComponent(sessionId)}/send-update`, {
    method: "POST",
    body,
  });
}

export function requestTodaySessionFeedback(sessionId: string) {
  return requestJson(`/app/api/sessions/${encodeURIComponent(sessionId)}/request-feedback`, {
    method: "POST",
  });
}

export function fetchTodayThreadTimeline(threadId: string) {
  return requestJson<Record<string, unknown>>(`/app/api/threads/${encodeURIComponent(threadId)}`);
}
