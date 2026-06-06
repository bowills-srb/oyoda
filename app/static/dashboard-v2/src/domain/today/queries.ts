import { queryOptions } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import {
  fetchTodayEscalations,
  fetchTodaySessionActions,
  fetchTodaySessionDetail,
  fetchTodaySessionWorkOrders,
  fetchTodaySessions,
  fetchTodayThreadTimeline,
} from "./api";
import {
  normalizeOpenEscalations,
  normalizeTodaySessionDetail,
  normalizeTodaySessionsList,
  normalizeTodayStayActions,
  normalizeTodayThreadTimeline,
} from "./normalize";
import type { SessionDetail } from "./types";

export function todaySessionsQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.today.sessions({ include_archived: false, limit: 200 }),
    queryFn: async () => normalizeTodaySessionsList(await fetchTodaySessions({ include_archived: false, limit: 200 })),
    staleTime: 15_000,
  });
}

export function todayEscalationsQueryOptions() {
  return queryOptions({
    queryKey: [...queryKeys.today.all(), "escalations"] as const,
    queryFn: async () => normalizeOpenEscalations(await fetchTodayEscalations()),
    staleTime: 15_000,
  });
}

export function todaySessionDetailQueryOptions(sessionId: string) {
  return queryOptions({
    queryKey: queryKeys.today.sessionDetail(sessionId),
    queryFn: async (): Promise<SessionDetail> => {
      const [rawDetail, rawWorkOrders] = await Promise.all([
        fetchTodaySessionDetail(sessionId),
        fetchTodaySessionWorkOrders(sessionId).catch(() => ({ work_orders: [] })),
      ]);
      const detail = normalizeTodaySessionDetail(rawDetail);
      const rawList = (rawWorkOrders as { work_orders?: unknown[] })?.work_orders;
      if (Array.isArray(rawList) && rawList.length > 0 && detail.workOrders.length === 0) {
        detail.workOrders = (rawList as Record<string, unknown>[]).map((order) => ({
          workOrderId: String(order.work_order_id || ""),
          workflowType: String(order.workflow_type || ""),
          workflowRef: String(order.workflow_ref || ""),
          propertyCode: String(order.property_code || ""),
          vendorId: String(order.vendor_id || ""),
          vendorName: String(order.vendor_name || ""),
          vendorPhone: String(order.vendor_phone || ""),
          issueCategory: String(order.issue_category || ""),
          status: String(order.status || ""),
          priority: String(order.priority || ""),
          summary: String(order.summary || ""),
          details: String(order.details || ""),
          dispatchState: String(order.dispatch_state || ""),
          etaMinutes: order.eta_minutes == null ? null : Number(order.eta_minutes),
          etaVisibilityMode: String(order.eta_visibility_mode || "estimated"),
          trackingUrl: String(order.tracking_url || ""),
          lastKnownDistanceText: String(order.last_known_distance_text || ""),
          assetId: String(order.asset_id || ""),
          verificationState: String(order.verification_state || ""),
          invoiceState: String(order.invoice_state || ""),
          invoiceAmount: order.invoice_amount == null ? null : Number(order.invoice_amount),
          invoiceReference: String(order.invoice_reference || ""),
          lastActorLabel: String(order.last_actor_label || ""),
          payload: order.payload && typeof order.payload === "object" ? (order.payload as Record<string, unknown>) : {},
          resolution: order.resolution && typeof order.resolution === "object" ? (order.resolution as Record<string, unknown>) : {},
          createdAt: (order.created_at as string | null | undefined) || null,
          updatedAt: (order.updated_at as string | null | undefined) || null,
          acceptedAt: (order.accepted_at as string | null | undefined) || null,
          scheduledAt: (order.scheduled_at as string | null | undefined) || null,
          completedAt: (order.completed_at as string | null | undefined) || null,
          verifiedAt: (order.verified_at as string | null | undefined) || null,
          closedAt: (order.closed_at as string | null | undefined) || null,
        }));
      }
      return detail;
    },
    staleTime: 15_000,
  });
}

export function todaySessionActionsQueryOptions(sessionId: string) {
  return queryOptions({
    queryKey: queryKeys.today.sessionActions(sessionId),
    queryFn: async () => normalizeTodayStayActions(await fetchTodaySessionActions(sessionId)),
    staleTime: 15_000,
  });
}

export function todayThreadTimelineQueryOptions(threadId: string) {
  return queryOptions({
    queryKey: queryKeys.today.threadTimeline(threadId),
    queryFn: async () => normalizeTodayThreadTimeline(await fetchTodayThreadTimeline(threadId)),
    staleTime: 60_000,
  });
}
