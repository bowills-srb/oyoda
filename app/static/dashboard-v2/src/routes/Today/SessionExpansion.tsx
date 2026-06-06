import { useEffect, useMemo, useRef, useState } from "react";

import { Badge } from "../../components/primitives/Badge";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import type { SessionDetail, StayActions, ThreadTimeline, TodaySessionsList } from "../../domain/today/types";
import type { LifecycleClassification } from "../../shared/lifecycle/windows";
import { cn } from "../../lib/utils";

import { labelForAction } from "./actionLabels";
import { formatAge } from "./lifecycleLabels";
import { deriveTimeline } from "./timeline";

/**
 * SessionExpansion — the inline expanded row.
 *
 * Renders an Actions block plus four read-only blocks under a queue card
 * when the row is selected:
 *   0. Actions             — AI-recommended next steps + always-available
 *                            operator tools (Reassure, Request feedback).
 *                            New in step 6.
 *   1. Stay timeline strip — dots for each operational touch on this stay
 *   2. Open work orders    — vendor work items with dispatch state and ETA
 *   3. Conversation snippet — last 4 messages, direction-tagged
 *   4. Cross-session history — prior touches with this guest by thread id
 *
 * Action execution model:
 *   - Each queued action is rendered as a button. Status "ready" is
 *     clickable; "in_progress" shows a spinner; "failed" shows a retry;
 *     "blocked" is muted with the suppression reason.
 *   - The route owns the local in-flight set (executingKeys) so a click
 *     visually commits before the refetch lands. Pure refetch follows for
 *     correctness — the route patches detail/actions caches when the API
 *     call returns.
 *   - Message-sending actions show a preview of payload.message_text
 *     before the operator confirms. The operator either sends as-is or
 *     ignores; custom-text path is Reassure.
 *   - Operator tools (Reassure, Request feedback) are always visible (when
 *     their preconditions hold) — they're not queued by the agent, they're
 *     bound-to-row.
 *
 * Click handlers inside the expansion stopPropagation so they don't
 * re-trigger the parent row's onClick.
 */

type Session = TodaySessionsList["sessions"][number];
type StayAction = StayActions["actions"][number];
type DetailNotification = SessionDetail["notifications"][number];

// Local action keys for the operator-tools section. These don't have an
// action_type in the backend queue — they're route-bound shortcuts that
// call dedicated endpoints. We use these keys for the executingKeys set
// so they share the in-flight machinery with queued actions.
export const OPERATOR_TOOL_REASSURE = "operator:reassure";
export const OPERATOR_TOOL_REQUEST_FEEDBACK = "operator:request_feedback";

type ProactiveListItem = {
  key: string;
  label: string;
  context?: string;
  age?: string;
};

type ProactiveBadgeItem = {
  key: string;
  label: string;
  tone: "default" | "accent" | "warning" | "success";
};

type ProactiveRecommendation = {
  label: string;
  tone: "default" | "accent" | "warning";
  message: string;
  backoff: string;
};

type ProactiveJourneyBlock = {
  primaryLabel: string;
  primaryTouches: ProactiveListItem[];
  recommendation: ProactiveRecommendation | null;
  activities: ProactiveBadgeItem[];
  notificationsLabel: string;
  notifications: ProactiveListItem[];
};

function humanizeSnake(value: string): string {
  if (!value) return "";
  return value
    .split("_")
    .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : part))
    .join(" ");
}

function inferContextualTouch(notification: DetailNotification): string | null {
  const haystack = [
    notification.notificationType,
    notification.externalId,
    notification.errorMessage,
  ]
    .join(" ")
    .toLowerCase();
  if (!haystack) return null;
  if (haystack.includes("red_flag") || haystack.includes("beach_flag") || haystack.includes("flag")) {
    return "Conditions touch (inferred)";
  }
  if (haystack.includes("weather") || haystack.includes("rain") || haystack.includes("storm")) {
    return "Weather touch (inferred)";
  }
  if (haystack.includes("heat") || haystack.includes("market") || haystack.includes("demand")) {
    return "Planning touch (inferred)";
  }
  return null;
}

function deriveProactiveJourneyBlock(
  detail: SessionDetail | null,
  classification: LifecycleClassification,
): ProactiveJourneyBlock | null {
  if (!detail) return null;

  const journey = detail.journey;
  const notifications = detail.notifications.slice().sort((a, b) => {
    const aTime = new Date(a.deliveredAt || a.sentAt || 0).getTime();
    const bTime = new Date(b.deliveredAt || b.sentAt || 0).getTime();
    return bTime - aTime;
  });
  const workflowProactive =
    detail.workflow && detail.workflow.proactive && typeof detail.workflow.proactive === "object"
      ? detail.workflow.proactive
      : null;

  const primaryTouches: ProactiveListItem[] = [];
  if (journey.welcomeSent) {
    primaryTouches.push({
      key: "welcome",
      label: "Welcome sent",
      age: journey.welcomeSentAt ? `${formatAge(journey.welcomeSentAt)} ago` : "",
    });
  }
  if (journey.checkinReminderSent) {
    primaryTouches.push({
      key: "checkin_reminder",
      label: "Check-in reminder sent",
      age: journey.checkinReminderSentAt ? `${formatAge(journey.checkinReminderSentAt)} ago` : "",
    });
  }
  if (journey.checkoutReminderSent) {
    primaryTouches.push({
      key: "checkout_reminder",
      label: "Check-out reminder sent",
      age: journey.checkoutReminderSentAt ? `${formatAge(journey.checkoutReminderSentAt)} ago` : "",
    });
  }
  if (journey.extendOfferSent) {
    primaryTouches.push({
      key: "extend_offer",
      label: "Extend offer sent",
      context: journey.extendOfferResponse ? `Response: ${journey.extendOfferResponse}` : "",
      age: journey.extendOfferSentAt ? `${formatAge(journey.extendOfferSentAt)} ago` : "",
    });
  }
  if (journey.poolHeatOffered || journey.poolHeatAccepted) {
    primaryTouches.push({
      key: "pool_heat",
      label: journey.poolHeatAccepted ? "Pool heat accepted" : "Pool heat offered",
    });
  }

  const contextualNotifications = notifications
    .map((notification) => {
      const inferred = inferContextualTouch(notification);
      if (!inferred) return null;
      return {
        key: notification.notificationId || `${notification.notificationType}:${notification.sentAt || "unknown"}`,
        label: inferred,
        context: `${humanizeSnake(notification.notificationType || "notification")} · ${notification.channel || "unknown channel"} · ${notification.status || "status unknown"}`,
        age: notification.deliveredAt || notification.sentAt ? `${formatAge(notification.deliveredAt || notification.sentAt)} ago` : "",
      } satisfies ProactiveListItem;
    })
    .filter(Boolean) as ProactiveListItem[];

  const genericNotifications = notifications.slice(0, 4).map((notification) => ({
    key: notification.notificationId || `${notification.notificationType}:${notification.sentAt || "unknown"}`,
    label: humanizeSnake(notification.notificationType || "notification"),
    context: `${notification.channel || "unknown channel"} · ${notification.status || "status unknown"}`,
    age: notification.deliveredAt || notification.sentAt ? `${formatAge(notification.deliveredAt || notification.sentAt)} ago` : "",
  }));

  const activities = journey.activities.map((activity) => ({
    key: activity.activityId || activity.activityType,
    label: `${humanizeSnake(activity.activityType)} · ${humanizeSnake(activity.status || "not_discussed")}`,
    tone:
      activity.status === "booked" || activity.status === "handled"
        ? "success"
        : activity.status === "info_provided"
          ? "accent"
          : "default",
  })) satisfies ProactiveBadgeItem[];

  let recommendation: ProactiveRecommendation | null = null;
  if (workflowProactive) {
    const touchType = String(workflowProactive.touch_type || "");
    const message = String(workflowProactive.message || "");
    const backoff = String(workflowProactive.backoff_reason || "");
    const eligible = workflowProactive.eligible === true;
    recommendation = {
      label: eligible ? `${humanizeSnake(touchType || "proactive touch")} due` : "No touch due right now",
      tone: eligible ? "warning" : backoff ? "default" : "accent",
      message,
      backoff,
    };
  }

  if (classification.bucket === "pre_arrival") {
    return {
      primaryLabel: "Journey milestones",
      primaryTouches,
      recommendation,
      activities,
      notificationsLabel: "Recent guest touches",
      notifications: genericNotifications,
    };
  }

  if (classification.bucket === "arriving") {
    return {
      primaryLabel: "Arrival readiness",
      primaryTouches,
      recommendation,
      activities,
      notificationsLabel: "Recent arrival touches",
      notifications: genericNotifications,
    };
  }

  if (classification.bucket === "in_stay") {
    return {
      primaryLabel: "Conditions-aware touches",
      primaryTouches: contextualNotifications.length > 0 ? contextualNotifications : primaryTouches,
      recommendation,
      activities,
      notificationsLabel: contextualNotifications.length > 0 ? "Recent guest touches" : "Notification history",
      notifications: contextualNotifications.length > 0 ? genericNotifications : genericNotifications,
    };
  }

  return {
    primaryLabel: "Departure follow-through",
    primaryTouches,
    recommendation,
    activities,
    notificationsLabel: "Recent guest touches",
    notifications: genericNotifications,
  };
}

export type SessionExpansionProps = {
  session: Session;
  classification: LifecycleClassification;
  detail: SessionDetail | null;
  threadTimeline: ThreadTimeline | null;
  actions: StayAction[] | null;
  executingKeys: Set<string>;
  actionError: { key: string; message: string } | null;
  isLoading: boolean;
  error: string;
  onClose: () => void;
  onExecuteAction: (actionType: string) => void;
  onReassure: (messageText: string) => void;
  onRequestFeedback: () => void;
};

export function SessionExpansion({
  session,
  classification,
  detail,
  threadTimeline,
  actions,
  executingKeys,
  actionError,
  isLoading,
  error,
  onClose,
  onExecuteAction,
  onReassure,
  onRequestFeedback,
}: SessionExpansionProps) {
  const timeline = useMemo(() => deriveTimeline(detail), [detail]);

  // The expansion only renders the work orders that are still operational.
  // Closed / verified / failed orders are operational history rather than
  // current work; they belong to the timeline strip's view of the past.
  const openWorkOrders = useMemo(() => {
    if (!detail) return [];
    const terminal = new Set(["closed", "completed", "verified", "cancelled"]);
    return detail.workOrders.filter((order) => !terminal.has(order.status.toLowerCase()));
  }, [detail]);

  // Conversation snippet: last 4 messages, oldest-first so the most recent
  // is at the bottom (matches chat-style reading). Full thread browsing is
  // not in scope here.
  const recentMessages = useMemo(() => {
    if (!detail) return [];
    const all = detail.messages.slice();
    all.sort((a, b) => {
      const aTime = a.createdAt ? new Date(a.createdAt).getTime() : 0;
      const bTime = b.createdAt ? new Date(b.createdAt).getTime() : 0;
      return aTime - bTime;
    });
    return all.slice(-4);
  }, [detail]);

  // Cross-session history excludes the current session itself — the row
  // already shows the current stay's context, so repeating it inside the
  // history block would be noisy.
  const crossSessionItems = useMemo(() => {
    if (!threadTimeline) return [];
    return threadTimeline.timeline.filter((item) => {
      if (item.itemType === "session" && item.itemId === session.sessionId) return false;
      return true;
    });
  }, [threadTimeline, session.sessionId]);

  // Filter the queued actions to ones that should surface in the UI.
  // Completed actions are hidden — they've already happened and the
  // timeline strip / message snippet reflect them. The others render with
  // status-appropriate affordances.
  const visibleActions = useMemo(() => {
    if (!actions) return [];
    return actions.filter((action) => {
      const status = (action.status || "").toLowerCase();
      return status !== "completed";
    });
  }, [actions]);

  // Show the operator-tools section when at least one tool is applicable.
  const canReassure = Boolean(session.guestPhone);
  const canRequestFeedback = Boolean(detail?.postStayActions?.canRequestFeedback);
  const showOperatorTools = canReassure || canRequestFeedback;

  // Show the Actions block whenever there's anything to render, including
  // operator tools. If nothing applies, the block collapses entirely
  // rather than showing an empty header.
  const showActionsBlock = visibleActions.length > 0 || showOperatorTools;

  const proactiveBlock = useMemo(
    () => deriveProactiveJourneyBlock(detail, classification),
    [detail, classification],
  );

  return (
    <div
      className="border-t border-hairline bg-raised"
      onClick={(event) => event.stopPropagation()}
    >
      <div className="flex items-center justify-end px-5 py-3 border-b border-hairline">
        <button
          type="button"
          className="text-xs font-medium text-tertiary hover:text-primary transition-colors duration-100 border-0 bg-transparent cursor-pointer px-2 py-1 rounded"
          onClick={onClose}
          aria-label="Close expanded session"
        >
          Close
        </button>
      </div>

      {error ? (
        <div className="px-5 py-4 grid gap-3 border-t border-hairline">
          <p className="m-0 text-[13px] text-tertiary leading-relaxed">Couldn't load session detail: {error}</p>
        </div>
      ) : isLoading && !detail ? (
        <div className="px-5 py-4 grid gap-3 border-t border-hairline">
          <p className="m-0 text-[13px] text-tertiary leading-relaxed">Loading session detail…</p>
        </div>
      ) : detail ? (
        <>
          {/* Block 0: actions */}
          {showActionsBlock ? (
            <div className="px-5 py-4 grid gap-3 border-t border-hairline">
              <span className="text-[10.5px] font-medium text-tertiary uppercase tracking-[0.06em] leading-none">Actions</span>

              {visibleActions.length > 0 ? (
                <ul className="m-0 p-0 list-none flex flex-col gap-2.5">
                  {visibleActions.map((action) => (
                    <ActionRow
                      key={action.actionType}
                      action={action}
                      isExecuting={executingKeys.has(action.actionType)}
                      error={
                        actionError && actionError.key === action.actionType
                          ? actionError.message
                          : ""
                      }
                      onExecute={() => onExecuteAction(action.actionType)}
                    />
                  ))}
                </ul>
              ) : null}

              {showOperatorTools ? (
                <div className="flex flex-col gap-3 mt-3 pt-3 border-t border-hairline">
                  {canReassure ? (
                    <ReassureControl
                      isExecuting={executingKeys.has(OPERATOR_TOOL_REASSURE)}
                      error={
                        actionError && actionError.key === OPERATOR_TOOL_REASSURE
                          ? actionError.message
                          : ""
                      }
                      onSend={onReassure}
                    />
                  ) : null}

                  {canRequestFeedback ? (
                    <RequestFeedbackControl
                      suggestion={detail.postStayActions.feedbackPromptSuggestion}
                      isExecuting={executingKeys.has(OPERATOR_TOOL_REQUEST_FEEDBACK)}
                      error={
                        actionError && actionError.key === OPERATOR_TOOL_REQUEST_FEEDBACK
                          ? actionError.message
                          : ""
                      }
                      onSend={onRequestFeedback}
                    />
                  ) : null}
                </div>
              ) : null}
            </div>
          ) : null}

          {/* Block 0.5: proactive journey */}
          <div className="px-5 py-4 grid gap-3 border-t border-hairline">
            <span className="text-[10.5px] font-medium text-tertiary uppercase tracking-[0.06em] leading-none">Proactive journey</span>
            {!proactiveBlock ? (
              <p className="m-0 text-[13px] text-tertiary leading-relaxed">No proactive journey context recorded yet.</p>
            ) : (
              <div className="grid gap-3">
                {proactiveBlock.primaryTouches.length > 0 ? (
                  <div className="grid gap-2">
                    <span className="text-[10.5px] font-semibold text-tertiary uppercase tracking-[0.04em]">{proactiveBlock.primaryLabel}</span>
                    <ul className="m-0 p-0 list-none grid gap-2">
                      {proactiveBlock.primaryTouches.map((item) => (
                        <li key={item.key} className="flex items-start justify-between gap-3">
                          <span className="grid gap-0.5 min-w-0">
                            <strong className="text-[12.5px] font-semibold text-primary">{item.label}</strong>
                            {item.context ? <span className="text-xs text-secondary leading-[1.5]">{item.context}</span> : null}
                          </span>
                          {item.age ? <span className="text-[11.5px] text-tertiary whitespace-nowrap">{item.age}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {proactiveBlock.recommendation ? (
                  <div className="grid gap-2">
                    <span className="text-[10.5px] font-semibold text-tertiary uppercase tracking-[0.04em]">Current recommendation</span>
                    <div className="grid gap-2">
                      <div className="flex items-center gap-2 flex-wrap">
                        <Badge tone={proactiveBlock.recommendation.tone}>
                          {proactiveBlock.recommendation.label}
                        </Badge>
                        {proactiveBlock.recommendation.backoff ? (
                          <span className="text-[11.5px] text-tertiary whitespace-nowrap">
                            Backing off · {proactiveBlock.recommendation.backoff}
                          </span>
                        ) : null}
                      </div>
                      {proactiveBlock.recommendation.message ? (
                        <p className="m-0 text-[13px] text-secondary leading-relaxed">{proactiveBlock.recommendation.message}</p>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                {proactiveBlock.activities.length > 0 ? (
                  <div className="grid gap-2">
                    <span className="text-[10.5px] font-semibold text-tertiary uppercase tracking-[0.04em]">Activity planning</span>
                    <ul className="m-0 p-0 list-none flex gap-2 flex-wrap">
                      {proactiveBlock.activities.map((activity) => (
                        <li key={activity.key}>
                          <Badge tone={activity.tone}>{activity.label}</Badge>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {proactiveBlock.notifications.length > 0 ? (
                  <div className="grid gap-2">
                    <span className="text-[10.5px] font-semibold text-tertiary uppercase tracking-[0.04em]">{proactiveBlock.notificationsLabel}</span>
                    <ul className="m-0 p-0 list-none grid gap-2">
                      {proactiveBlock.notifications.map((item) => (
                        <li key={item.key} className="flex items-start justify-between gap-3">
                          <span className="grid gap-0.5 min-w-0">
                            <strong className="text-[12.5px] font-semibold text-primary">{item.label}</strong>
                            {item.context ? <span className="text-xs text-secondary leading-[1.5]">{item.context}</span> : null}
                          </span>
                          {item.age ? <span className="text-[11.5px] text-tertiary whitespace-nowrap">{item.age}</span> : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            )}
          </div>

          {/* Block 1: stay timeline strip */}
          <div className="px-5 py-4 grid gap-3 border-t border-hairline">
            <span className="text-[10.5px] font-medium text-tertiary uppercase tracking-[0.06em] leading-none">Stay timeline</span>
            {timeline.length === 0 ? (
              <p className="m-0 text-[13px] text-tertiary leading-relaxed">No operational events recorded yet.</p>
            ) : (
              <ol className="m-0 p-0 list-none flex gap-2 flex-wrap" aria-label="Stay lifecycle events">
                {timeline.map((dot) => (
                  <li
                    key={dot.key}
                    className="flex flex-col items-center gap-1 min-w-0 cursor-default"
                    title={dot.occurredAt ? `${dot.label} · ${formatAge(dot.occurredAt)} ago` : dot.label}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "w-2 h-2 rounded-full flex-shrink-0",
                        dot.tone === "done" && "bg-[var(--success-500)]",
                        dot.tone === "alert" && "bg-[var(--danger-500)]",
                        dot.tone === "pending" && "bg-[var(--border-default)]",
                        !dot.tone && "bg-[var(--border-default)]",
                      )}
                    />
                    <span className="text-[10.5px] text-tertiary leading-tight text-center">{dot.label}</span>
                    {dot.occurredAt ? (
                      <span className="text-[10px] text-tertiary opacity-70">{formatAge(dot.occurredAt)}</span>
                    ) : null}
                  </li>
                ))}
              </ol>
            )}
          </div>

          {/* Block 2: open work orders */}
          <div className="px-5 py-4 grid gap-3 border-t border-hairline">
            <span className="text-[10.5px] font-medium text-tertiary uppercase tracking-[0.06em] leading-none">Open work orders</span>
            {openWorkOrders.length === 0 ? (
              <p className="m-0 text-[13px] text-tertiary leading-relaxed">No open work orders.</p>
            ) : (
              <ul className="m-0 p-0 list-none grid gap-2">
                {openWorkOrders.map((order) => {
                  const dispatchLabel = order.dispatchState
                    ? order.dispatchState.replace(/_/g, " ")
                    : "";
                  const eta = order.etaMinutes != null && order.etaMinutes > 0
                    ? ` · ETA ${order.etaMinutes}m`
                    : "";
                  return (
                    <li key={order.workOrderId} className="grid gap-1">
                      <div className="flex items-center justify-between gap-2">
                        <strong className="text-[13px] font-medium text-primary">{order.vendorName || order.issueCategory || "Work order"}</strong>
                        {dispatchLabel ? (
                          <Badge tone="warning">
                            {dispatchLabel}
                            {eta}
                          </Badge>
                        ) : null}
                      </div>
                      {order.summary ? (
                        <p className="m-0 text-xs text-tertiary">{order.summary}</p>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {/* Block 3: conversation snippet */}
          <div className="px-5 py-4 grid gap-3 border-t border-hairline">
            <span className="text-[10.5px] font-medium text-tertiary uppercase tracking-[0.06em] leading-none">Recent conversation</span>
            {recentMessages.length === 0 ? (
              <p className="m-0 text-[13px] text-tertiary leading-relaxed">No messages yet on this stay.</p>
            ) : (
              <ul className="m-0 p-0 list-none grid gap-3">
                {recentMessages.map((message) => (
                  <li
                    key={message.messageId}
                    className={cn("grid gap-0.5", message.direction === "outbound" && "items-end")}
                  >
                    <span className="text-[10.5px] text-tertiary">
                      {message.direction === "inbound" ? session.guestName || "Guest" : "Operator"}
                      {message.createdAt ? ` · ${formatAge(message.createdAt)} ago` : ""}
                    </span>
                    <p className="m-0 text-[13px] text-secondary leading-relaxed">{message.content}</p>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Block 4: cross-session history, only when there's something to show */}
          {crossSessionItems.length > 0 ? (
            <div className="px-5 py-4 grid gap-3 border-t border-hairline">
              <span className="text-[10.5px] font-medium text-tertiary uppercase tracking-[0.06em] leading-none">Prior history with this guest</span>
              <ul className="m-0 p-0 list-none grid gap-2">
                {crossSessionItems.map((item) => (
                  <li key={`${item.itemType}:${item.itemId}`} className="grid grid-cols-[auto_1fr_auto] gap-2 items-baseline text-xs">
                    <span className="text-tertiary font-medium capitalize">{item.itemType.replace(/_/g, " ")}</span>
                    <span className="text-secondary truncate">{item.summary || "—"}</span>
                    {item.occurredAt ? (
                      <span className="text-tertiary whitespace-nowrap">{formatAge(item.occurredAt)} ago</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// ActionRow — one row in the queued-actions list
// ────────────────────────────────────────────────────────────────────────────
//
// Renders a single queued action. Behavior depends on the action's status:
//   ready       — clickable, primary tone
//   in_progress — disabled with "Sending…" / "Running…" label
//   failed      — muted with the failure message, offers a Retry button
//   blocked     — muted with the suppression reason, not clickable
//
// For message-sending action types (proactive_outreach, guest_status_response,
// guest_eta_update) the row shows a preview of payload.message_text inside a
// collapsible affordance so the operator can read what's about to go out
// before confirming.

function ActionRow({
  action,
  isExecuting,
  error,
  onExecute,
}: {
  action: StayAction;
  isExecuting: boolean;
  error: string;
  onExecute: () => void;
}) {
  const labelInfo = labelForAction(action.actionType);
  const status = (action.status || "").toLowerCase();
  const [previewOpen, setPreviewOpen] = useState(false);

  // The brain stores the pre-composed text under payload.message_text for
  // every message-sending action type. Read defensively — payload is typed
  // as Record<string, unknown> at the adapter boundary.
  const previewText = labelInfo.sendsGuestMessage
    ? String((action.payload as { message_text?: unknown })?.message_text || "")
    : "";

  const isBlocked = status === "blocked";
  const isFailed = status === "failed";
  // Treat in_progress as "either the backend says it's running" OR
  // "the local in-flight set has it". The local set wins for immediacy
  // since the backend can take a beat to update its own state.
  const inFlight = isExecuting || status === "in_progress";

  // Suppression reason for blocked actions: the agent writes this to
  // result_json with keys like suppressed_reason / message. Render the
  // first one we find so the operator understands why the action is
  // unactionable.
  const suppressionReason = isBlocked
    ? String(
        (action.result as { suppressed_reason?: unknown; message?: unknown })?.suppressed_reason ||
          (action.result as { message?: unknown })?.message ||
          "Action is currently blocked",
      )
    : "";

  // Verb shown on the button. For message-sending actions, "Send" is more
  // operationally honest than the action's generic label ("Send proactive
  // update" → "Send" when previewing because the operator already sees what
  // they're sending).
  const buttonLabel = inFlight
    ? labelInfo.sendsGuestMessage
      ? "Sending…"
      : "Running…"
    : isFailed
      ? "Retry"
      : labelInfo.label;

  return (
    <li className={cn(
      "flex flex-col gap-2 p-3.5 border rounded-[10px] bg-raised",
      isFailed && "border-[color-mix(in_srgb,var(--danger-spine)_30%,transparent)] bg-[var(--danger-fill)]",
      isBlocked && "border-hairline bg-[var(--surface-sunken)] opacity-85",
      !isFailed && !isBlocked && "border-hairline",
    )}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1 min-w-0">
          <strong className="text-sm font-[620] text-primary">{labelInfo.label}</strong>
          <span className="text-[11.5px] leading-[1.45] text-tertiary">{labelInfo.description}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {labelInfo.sendsGuestMessage && previewText ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setPreviewOpen((open) => !open)}
              aria-expanded={previewOpen}
            >
              {previewOpen ? "Hide preview" : "Preview"}
            </Button>
          ) : null}
          {isBlocked ? (
            <Badge tone="default">Blocked</Badge>
          ) : (
            <Button
              type="button"
              variant={isFailed ? "danger" : "default"}
              size="sm"
              onClick={onExecute}
              disabled={inFlight}
            >
              {buttonLabel}
            </Button>
          )}
        </div>
      </div>

      {previewOpen && previewText ? (
        <blockquote className="m-0 mt-1 p-[10px_12px] border-l-[3px] border-l-accent bg-[var(--surface-sunken)] text-primary text-[12.5px] leading-[1.55] whitespace-pre-wrap">{previewText}</blockquote>
      ) : null}

      {isFailed ? (
        <p className="m-0 text-xs text-[var(--danger-600)]">
          {String(
            (action.result as { message?: unknown })?.message || "Action failed; tap Retry to run again.",
          )}
        </p>
      ) : null}

      {isBlocked && suppressionReason ? (
        <p className="m-0 text-xs text-secondary">{suppressionReason}</p>
      ) : null}

      {error ? <p className="m-0 text-xs text-[var(--danger-600)]">{error}</p> : null}
    </li>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// ReassureControl — operator-typed message bound to sessions.sendUpdate
// ────────────────────────────────────────────────────────────────────────────
//
// Always visible when the session has a guestPhone. The operator types a
// custom message and clicks Send; the backend routes it through
// channel_router (the safe operator-app path). This is the escape hatch
// when no queued action carries the message the operator wants to send.

function ReassureControl({
  isExecuting,
  error,
  onSend,
}: {
  isExecuting: boolean;
  error: string;
  onSend: (messageText: string) => void;
}) {
  const [text, setText] = useState("");
  // Track the prior isExecuting so we can detect the true→false edge.
  // A ref (not state) because we only need the value across renders for
  // comparison — changing it should not retrigger anything.
  const wasExecutingRef = useRef(false);

  // Draft preservation: clear the textarea only when an in-flight send
  // finishes successfully (isExecuting just went false and there's no
  // error for this control). On failure the operator keeps their text
  // and can edit/retry without retyping. This matters because Reassure
  // is the only freeform outbound path in the row — a lost draft here
  // has real recovery cost; every other send is a pre-composed queued
  // action where the operator's input was just "click".
  useEffect(() => {
    if (wasExecutingRef.current && !isExecuting && !error) {
      setText("");
    }
    wasExecutingRef.current = isExecuting;
  }, [isExecuting, error]);

  const trimmed = text.trim();
  const canSend = !isExecuting && trimmed.length > 0;

  return (
    <div className="flex flex-col gap-2 p-3.5 border border-hairline rounded-[10px] bg-raised">
      <label className="flex flex-col gap-1.5 text-[13px] font-semibold text-primary">
        Reassure guest
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Type a quick message to the guest…"
          rows={2}
          disabled={isExecuting}
        />
      </label>
      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          onClick={() => {
            if (!canSend) return;
            // Do NOT clear text here. The effect above clears it only
            // after a successful send completes. Clearing eagerly would
            // destroy the operator's draft on a failed send.
            onSend(trimmed);
          }}
          disabled={!canSend}
        >
          {isExecuting ? "Sending…" : "Send"}
        </Button>
      </div>
      {error ? <p className="m-0 text-xs text-[var(--danger-600)]">{error}</p> : null}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────────────────
// RequestFeedbackControl — single-click post-stay feedback request
// ────────────────────────────────────────────────────────────────────────────
//
// Visible when detail.postStayActions.canRequestFeedback is true. The
// backend's request-feedback endpoint records a feedback_requested event
// and returns a suggested message; the operator clicks once to commit.

function RequestFeedbackControl({
  suggestion,
  isExecuting,
  error,
  onSend,
}: {
  suggestion: string;
  isExecuting: boolean;
  error: string;
  onSend: () => void;
}) {
  // IMPORTANT: this control does NOT send a message to the guest. The
  // backend's /sessions/{id}/request-feedback endpoint records a
  // feedback_requested event and returns a suggested_message string for
  // the operator to use later. Nothing reaches the guest from this click.
  //
  // Copy is framed around logging the request and offering the suggested
  // text as a starting point, not as preview-of-outbound. "Logging…" in
  // the in-flight state matches the actual backend behavior; "Send…"
  // would mislead the operator into thinking a message went out.
  return (
    <div className="flex flex-col gap-2 p-3.5 border border-hairline rounded-[10px] bg-raised">
      <div className="flex flex-col gap-0.5">
        <strong>Log feedback request</strong>
        <span className="text-[11.5px] leading-[1.45] text-tertiary">
          Records a feedback request for this guest. Doesn't send anything —
          use the suggested message below when you reach out.
        </span>
      </div>
      {suggestion ? (
        <>
          <span className="text-[11px] text-tertiary uppercase tracking-[0.04em] mt-1">Suggested message</span>
          <blockquote className="m-0 mt-1 p-[10px_12px] border-l-[3px] border-l-accent bg-[var(--surface-sunken)] text-primary text-[12.5px] leading-[1.55] whitespace-pre-wrap">{suggestion}</blockquote>
        </>
      ) : null}
      <div className="flex justify-end">
        <Button
          type="button"
          size="sm"
          onClick={onSend}
          disabled={isExecuting}
        >
          {isExecuting ? "Logging…" : "Log request"}
        </Button>
      </div>
      {error ? <p className="m-0 text-xs text-[var(--danger-600)]">{error}</p> : null}
    </div>
  );
}
