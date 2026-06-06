import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useListKeyboardNav } from "../../shared/hooks/useListKeyboardNav";

import { Badge } from "../../components/primitives/Badge";
import { SurfaceHeader } from "../../components/system/SurfaceHeader";
import { autonomyQueryOptions } from "../../domain/autonomy/queries";
import { dashboardSummaryQueryOptions } from "../../domain/dashboard/queries";
import { sessionQueryOptions } from "../../domain/auth/queries";
import type { AutonomyPayload } from "../../domain/autonomy/types";
import { fetchPreBookingBootstrap, suggestPropertyLinks } from "../../domain/prebooking/api";
import {
  applyBootstrapSnapshot,
  applyCachedBootstrapSnapshot,
  clearCachedBootstrapSnapshot,
  isBootstrapSnapshotFresh,
  getBootstrapSnapshot,
  loadMostRecentBootstrapSnapshot,
  loadCachedBootstrapSnapshot,
  persistBootstrapSnapshot,
} from "../../domain/prebooking/bootstrapCache";
import { useApproveInquiryMutation, useBindInquiryPropertyMutation, useEditInquiryMutation, useRejectInquiryMutation, useSaveAutonomyMutation } from "../../domain/prebooking/mutations";
import { preBookingMessageFeedQueryOptions } from "../../domain/prebooking/queries";
import type { BootstrapPayload, MessageFeed, MessageFeedItem, PropertyMatchSuggestion } from "../../domain/prebooking/types";
import { queryKeys } from "../../lib/query/queryKeys";
import { Icon } from "../../shared/Icon";
import { useUrlState } from "../../shared/url-state/useUrlState";
import type { SessionPayload } from "../../domain/auth/types";
import { PreBookingAutonomyPopover } from "./PreBookingAutonomyPopover";
import { PreBookingAssuranceBand } from "./PreBookingAssuranceBand";
import { PreBookingControls } from "./PreBookingControls";
import { PreBookingQueueShell } from "./PreBookingQueueShell";
import {
  buildQueueViewModel,
  type QueueDepth,
  type QueueMetricFocus,
  type QueueScope,
  type QueueTab,
} from "./viewModel";

/**
 * PreBookingRoute — operator inquiry queue surface.
 *
 * Extracted from the pre-router App.tsx with two structural changes and one
 * intentional non-change:
 *
 *   1. Sidebar moved to <Shell />. This file renders only the surface column.
 *   2. View state (active tab, filters, search, queue depth, focus metric,
 *      selected inquiry) lives in URL query params via useUrlState, not in
 *      the global store or sessionStorage. Selection writes use { replace }
 *      so clicking through rows doesn't fill back-button history.
 *   3. Data flow is being migrated from route-local fetches into typed domain
 *      queries and mutations so the route stops owning server-state plumbing.
 */

type BootstrapFreshness = "live" | "cached" | "stale";
// URL state defaults. useUrlState strips values equal to these defaults from
// the URL, so /app/v2/prebooking with no params represents the "open it
// fresh" view (tab=action, no filters, depth=25). queueDepth is stored as a
// string in URL ("5" | "10" | "25" | "50" | "all") and coerced at use sites.
const URL_DEFAULTS = {
  tab: "action",
  property: "",
  q: "",
  scope: "all",
  depth: "25",
  focus: "all",
  selected: "",
  // Focus mode: "1" collapses header + analytics/filter chrome so the queue
  // fills the screen for heads-down work. Stripped from URL when "0" (default).
  zen: "0",
};

const QUEUE_TABS: readonly QueueTab[] = ["action", "sent", "held", "closed"] as const;
const QUEUE_SCOPES: readonly QueueScope[] = ["all", "mine", "unassigned"] as const;
const QUEUE_FOCUSES: readonly QueueMetricFocus[] = [
  "all",
  "draft_ready",
  "knowledge_gap",
  "unbound",
] as const;

// URL coercion helpers. Each one snaps unknown values back to the default,
// which means the URL is always self-healing — a typo'd ?tab=actoin or a
// stale link with a removed enum value just renders the default rather than
// throwing. The function-level isolation also makes adding new enum members
// a one-line change.
function coerceTab(raw: string): QueueTab {
  return (QUEUE_TABS as readonly string[]).includes(raw) ? (raw as QueueTab) : "action";
}
function coerceScope(raw: string): QueueScope {
  return (QUEUE_SCOPES as readonly string[]).includes(raw) ? (raw as QueueScope) : "all";
}
function coerceFocus(raw: string): QueueMetricFocus {
  return (QUEUE_FOCUSES as readonly string[]).includes(raw) ? (raw as QueueMetricFocus) : "all";
}
function coerceDepth(raw: string): QueueDepth {
  if (raw === "all") return "all";
  const n = Number(raw);
  if (n === 5 || n === 10 || n === 25 || n === 50) return n;
  return 25;
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function formatPropertyScore(value?: number) {
  const score = typeof value === "number" ? Math.max(0, Math.min(1, value)) : 0;
  return `${Math.round(score * 100)}% match`;
}

function formatAge(timestamp?: string | null) {
  if (!timestamp) return "Now";
  const deltaMs = Date.now() - new Date(timestamp).getTime();
  if (!Number.isFinite(deltaMs) || deltaMs < 0) return "Now";
  const mins = Math.round(deltaMs / 60000);
  if (mins < 1) return "Now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

function getChannelLabel(item: MessageFeedItem) {
  const raw = (item.sourceProvider || item.channel || "").toLowerCase();
  if (raw.includes("vrbo")) return "Vrbo";
  if (raw.includes("airbnb")) return "Airbnb";
  if (raw.includes("booking")) return "Booking.com";
  if (raw.includes("escapia")) return "Escapia";
  if (raw === "sms" || raw === "rcs") return "SMS";
  if (raw === "email") return "Email";
  if (!raw) return "Email";
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

function wasHeldForReview(item: MessageFeedItem) {
  const status = (item.status || "").toLowerCase();
  if (status === "backlog_held") return true;
  if (status !== "pending_review") return false;
  if (item.draftSource === "kb_gap_required") return true;
  if (item.draftSource === "gmail_fallback_saved") return true;
  if (item.blockedByGapTopics?.length) return true;
  return false;
}

function isReviewableStatus(status?: string | null) {
  const normalized = (status || "").toLowerCase();
  return normalized === "pending_review" || normalized === "backlog_held";
}

function canOperatorSend(item: MessageFeedItem) {
  if (item.kind !== "inquiry") return false;
  if (!isReviewableStatus(item.status)) return false;
  if (!item.propertyId) return false;
  if (!item.draftText || !item.draftText.trim()) return false;
  if (item.draftSource === "kb_gap_required" || item.draftSource === "gmail_fallback_saved") return false;
  return true;
}

function getQueueBucket(item: MessageFeedItem): QueueTab {
  const status = item.status?.toLowerCase() || "pending_review";
  if (["replied", "sent", "auto_sent"].includes(status)) return "sent";
  if (["closed", "rejected", "expired", "archived", "resolved_without_reply"].includes(status)) return "closed";
  if (status === "pending_review" && wasHeldForReview(item)) return "held";
  return "action";
}

function getQueueTone(item: MessageFeedItem): "accent" | "warning" | "success" | "danger" | "default" {
  const bucket = getQueueBucket(item);
  if (bucket === "sent") return "success";
  if (bucket === "held") return "warning";
  if (!item.propertyId) return "danger";
  return "accent";
}

function getQueueLabel(item: MessageFeedItem) {
  const bucket = getQueueBucket(item);
  if (bucket === "sent") return item.triggeredBy === "auto_send" ? "Auto-sent" : "Sent";
  if (bucket === "held") return "Held";
  if (!item.propertyId) return "Unbound";
  if (item.draftReady || (item.confidence || 0) >= 0.85) return "Ready to send";
  return "Needs review";
}

function needsKnowledgeGap(item: MessageFeedItem) {
  return item.draftSource === "kb_gap_required" || item.draftSource === "gmail_fallback_saved";
}

function hasOperatorDraft(item: MessageFeedItem) {
  return Boolean(item.draftText && item.draftText.trim()) && !needsKnowledgeGap(item) && Boolean(item.propertyId);
}

function matchesMetricFocus(item: MessageFeedItem, focus: QueueMetricFocus) {
  if (focus === "all") return true;
  if (focus === "draft_ready") return isReviewableStatus(item.status) && hasOperatorDraft(item);
  if (focus === "knowledge_gap") return isReviewableStatus(item.status) && needsKnowledgeGap(item);
  if (focus === "unbound") return isReviewableStatus(item.status) && !item.propertyId;
  return true;
}

function getQueueSpineTone(item: MessageFeedItem) {
  if (getQueueBucket(item) === "sent") return "success";
  if (!item.propertyId && item.status === "pending_review") return "danger";
  if (item.draftSource === "kb_gap_required" || item.draftSource === "gmail_fallback_saved") return "warning";
  if ((item.confidence || 0) >= 0.85) return "accent";
  return "default";
}

// Operator-facing row state. Three values that map directly to "what should I do
// with this row": ready (send it), needs_review (look at the draft before
// deciding), blocked (something has to be fixed before the row can move).
//
// This is intentionally narrower than getQueueBucket. The queue bucket
// (action / sent / held / closed) is the queue-tab axis and stays as-is in
// the data model and URL state. The row state is what we render inside the
// Action tab so operators don't have to translate badge color + confidence
// number + draft availability into a verb every single row.
//
// Mapping rules:
//   blocked      — unbound (no propertyId), OR knowledge gap, OR no draft text
//                  on a reviewable row. These rows can't usefully move forward
//                  on a single click.
//   needs_review — bound + draft present + confidence below threshold OR
//                  below an absolute high-confidence floor (85%). These rows
//                  benefit from operator eyes before sending.
//   ready        — bound + draft present + high confidence. Single-click send
//                  is the right primary action.
//
// Sent and held rows fall through to a fourth value ("other") that we don't
// render a state chip for — they're on a different tab and the row visual
// language there is about status, not action.
export type RowState = "ready" | "needs_review" | "blocked" | "other";

function getRowState(item: MessageFeedItem, threshold: number): RowState {
  const bucket = getQueueBucket(item);
  if (bucket !== "action") return "other";
  if (!item.propertyId) return "blocked";
  if (needsKnowledgeGap(item)) return "blocked";
  if (!item.draftText || !item.draftText.trim()) return "blocked";
  const confidence = item.confidence || 0;
  // High-confidence floor: even if the operator's threshold is set lower
  // than 0.85, we still surface anything below 0.85 as needs_review so
  // operators don't get conditioned into rubber-stamping mid-confidence
  // drafts. The threshold drives auto-send eligibility, not row labels.
  const ready = item.draftReady || (confidence >= 0.85 && confidence >= threshold);
  return ready ? "ready" : "needs_review";
}

// Semantic confidence label for the row meta chip. Three buckets, deliberately
// coarse — the goal is "what do I do" not "how confident exactly". The exact
// percentage still appears inside the expanded view's confidence row for
// operators who want the precise number.
function getConfidenceLabel(confidence: number): { label: string; tone: "success" | "warning" | "danger" } {
  if (confidence >= 0.85) return { label: "High confidence", tone: "success" };
  if (confidence >= 0.6) return { label: "Needs review", tone: "warning" };
  return { label: "Low confidence", tone: "danger" };
}

function getNextStepGuidance(item: MessageFeedItem) {
  if (!item.propertyId) {
    return {
      tone: "danger" as const,
      title: "Next step: link this inquiry",
      body: "This inquiry is not bound to a property yet. Bind it first so the draft, policy checks, and send actions are grounded in the right listing.",
    };
  }
  if (wasHeldForReview(item)) {
    const missingTopics = item.blockedByGapTopics?.length
      ? ` Missing: ${item.blockedByGapTopics.join(", ")}.`
      : "";
    return {
      tone: "warning" as const,
      title: "Next step: unblock the hold",
      body:
        item.draftSource === "kb_gap_required" || item.draftSource === "gmail_fallback_saved"
          ? `This inquiry is waiting on property knowledge before it can return to the action queue.${missingTopics}`
          : "This inquiry is being held for review before it can move back into operator action.",
    };
  }
  if (!item.draftText?.trim()) {
    return {
      tone: "default" as const,
      title: "Next step: review before sending",
      body: "This inquiry is in the queue without a send-ready draft yet. Review the thread context before acting.",
    };
  }
  if (item.draftReady || (item.confidence || 0) >= 0.85) {
    return {
      tone: "accent" as const,
      title: "Next step: approve or personalize",
      body: "This draft looks ready. Send it as-is if it matches your intent, or edit it to add tone, commitments, or property-specific detail.",
    };
  }
  // Needs-review path. Surface *why* this row didn't qualify for Ready so the
  // operator can decide what to look for in the draft. Three common reasons:
  // (a) confidence below the 85% review floor, (b) confidence below the
  // operator's autonomy threshold even though it's above 85%, (c) the draft
  // came from a fallback path rather than the model. We attach the most
  // specific reason we can detect.
  const confidence = item.confidence || 0;
  let reason = "";
  if (item.draftSource && item.draftSource !== "model" && item.draftSource !== "messaging_brain") {
    reason = ` Draft was grounded from a fallback path (${item.draftSource.replace(/_/g, " ")}), not a full model generation.`;
  } else if (confidence > 0 && confidence < 0.85) {
    reason = ` Confidence is ${Math.round(confidence * 100)}%, below the 85% review floor.`;
  }
  return {
    tone: "default" as const,
    title: "Next step: operator review",
    body: `Review the draft carefully, then send it, edit it, or reject it. This row is actionable now; it is not waiting on another system.${reason}`,
  };
}

function formatBindingCandidateType(candidateType: string) {
  switch (candidateType) {
    case "platform_listing_id":
      return "Listing ID";
    case "platform_unit_id":
      return "Unit ID";
    case "property_code":
      return "Property code";
    case "raw_property_mention":
      return "Mentioned name";
    case "property_name":
      return "Property name";
    case "external_id_hint":
      return "External ID";
    default:
      return "Candidate";
  }
}

function preferredBindingQuery(item: MessageFeedItem) {
  const candidate = (item.propertyBindingCandidates || []).find((entry) => entry.value);
  if (candidate?.value) return candidate.value;
  return item.propertyName && item.propertyName !== "Unknown property" ? item.propertyName : "";
}

type LoadOptions = {
  force?: boolean;
};

function waitForBackgroundBootstrap() {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, 150);
  });
}

function waitForDeferredBootstrap(delayMs: number) {
  return new Promise<void>((resolve) => {
    window.setTimeout(resolve, delayMs);
  });
}

function waitForIdleBootstrap(delayMs: number) {
  return new Promise<void>((resolve) => {
    if (typeof window === "undefined") {
      resolve();
      return;
    }
    const idleCallback = (window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
    }).requestIdleCallback;
    if (typeof idleCallback === "function") {
      idleCallback(() => resolve(), { timeout: delayMs });
      return;
    }
    window.setTimeout(resolve, delayMs);
  });
}

async function loadSession(queryClient: QueryClient, options: LoadOptions = {}) {
  if (options.force) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.auth.session() });
  }
  return (await queryClient.fetchQuery(sessionQueryOptions())) as SessionPayload;
}

async function loadAutonomy(queryClient: QueryClient, options: LoadOptions = {}) {
  if (options.force) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.autonomy.current() });
  }
  return (await queryClient.fetchQuery(autonomyQueryOptions())) as AutonomyPayload;
}

async function loadMessageFeed(queryClient: QueryClient, options: LoadOptions = {}) {
  if (options.force) {
    await queryClient.invalidateQueries({ queryKey: queryKeys.prebooking.feed() });
  }
  return (await queryClient.fetchQuery(preBookingMessageFeedQueryOptions())) as MessageFeed;
}

async function loadBootstrap(queryClient: QueryClient) {
  const payload = (await fetchPreBookingBootstrap().catch((error: Error & { status?: number }) => {
    throw error;
  })) as BootstrapPayload;
  const snapshot = getBootstrapSnapshot(payload);
  if (!snapshot) throw new Error("Bootstrap payload missing tenant context");
  applyBootstrapSnapshot(snapshot, queryClient);
  persistBootstrapSnapshot(snapshot);
  return snapshot;
}

export default function PreBookingRoute() {
  const queryClient = useQueryClient();
  const hasHydratedFeedAtMount = Boolean(queryClient.getQueryData(queryKeys.prebooking.feed()));
  const hydratedSnapshot =
    hasHydratedFeedAtMount && typeof window !== "undefined" ? loadMostRecentBootstrapSnapshot() : null;
  const hasFreshHydratedBootstrap = isBootstrapSnapshotFresh(hydratedSnapshot, 60_000);
  const approveInquiryMutation = useApproveInquiryMutation();
  const rejectInquiryMutation = useRejectInquiryMutation();
  const editInquiryMutation = useEditInquiryMutation();
  const bindInquiryPropertyMutation = useBindInquiryPropertyMutation();
  const saveAutonomyMutation = useSaveAutonomyMutation();
  const [error, setError] = useState("");
  const [isBootstrapping, setIsBootstrapping] = useState(!hasHydratedFeedAtMount);
  const [bootstrapFreshness, setBootstrapFreshness] = useState<BootstrapFreshness>(
    hasFreshHydratedBootstrap ? "live" : hasHydratedFeedAtMount ? "cached" : "live",
  );
  const [pendingAction, setPendingAction] = useState<{ id: string; kind: "send" | "reject" | "edit" | "bind" } | null>(null);
  const [actionError, setActionError] = useState<string>("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<string>("");
  const [bindingDraftId, setBindingDraftId] = useState<string | null>(null);
  const [bindingQuery, setBindingQuery] = useState<string>("");
  const [bindingSuggestions, setBindingSuggestions] = useState<PropertyMatchSuggestion[]>([]);
  const [bindingLoading, setBindingLoading] = useState(false);
  const [bindingError, setBindingError] = useState("");
  const { data: session } = useQuery({ ...sessionQueryOptions(), enabled: false });
  const { data: autonomy } = useQuery({ ...autonomyQueryOptions(), enabled: false });
  const { data: feed } = useQuery({ ...preBookingMessageFeedQueryOptions(), enabled: false });
  const { data: dashboardSummary } = useQuery(dashboardSummaryQueryOptions());

  // URL state. urlState.tab / .property / .q / .scope / .depth / .focus /
  // .selected mirror what used to live in the global store under
  // preBookingUi. updateUrl(patch, options?) is the equivalent of the old
  // setPreBookingUi — one helper, same call-site shape, different
  // persistence underneath.
  const [urlState, updateUrl] = useUrlState(URL_DEFAULTS);
  const activeTab = coerceTab(urlState.tab);
  const propertyId = urlState.property;
  const search = urlState.q;
  const scope = coerceScope(urlState.scope);
  const queueDepth = coerceDepth(urlState.depth);
  const focusMetric = coerceFocus(urlState.focus);
  const focusMode = urlState.zen === "1";
  const selectedInquiryId = urlState.selected || null;

  const deferredSearch = useDeferredValue(search);

  useEffect(() => {
    let ignore = false;
    async function hydrateFromValidatedSession() {
      try {
        if (hasFreshHydratedBootstrap) return;
        if (hasHydratedFeedAtMount) {
          await waitForBackgroundBootstrap();
          if (ignore) return;
        }
        const liveSession = await loadSession(queryClient);
        if (ignore) return;
        const cached = loadCachedBootstrapSnapshot(liveSession);
        if (!cached) return;
        applyCachedBootstrapSnapshot(cached, liveSession, queryClient);
        setBootstrapFreshness("cached");
        setIsBootstrapping(false);
      } catch (err) {
        if (ignore) return;
        clearCachedBootstrapSnapshot();
        if ((err as { status?: number })?.status === 401 || (err as { status?: number })?.status === 403) {
          setBootstrapFreshness("live");
          queryClient.removeQueries({ queryKey: queryKeys.auth.all() });
          queryClient.removeQueries({ queryKey: queryKeys.autonomy.all() });
          queryClient.removeQueries({ queryKey: queryKeys.prebooking.all() });
        }
      }
    }
    void hydrateFromValidatedSession();
    return () => {
      ignore = true;
    };
  }, [hasFreshHydratedBootstrap, hasHydratedFeedAtMount, queryClient]);

  useEffect(() => {
    let ignore = false;
    async function prime() {
      if (!hasHydratedFeedAtMount) setIsBootstrapping(true);
      try {
        if (hasHydratedFeedAtMount) {
          if (hasFreshHydratedBootstrap) {
            await waitForIdleBootstrap(15_000);
          } else {
            await waitForBackgroundBootstrap();
          }
          if (ignore) return;
        }
        await loadBootstrap(queryClient);
        if (!ignore) {
          setBootstrapFreshness("live");
          setError("");
        }
      } catch (err) {
        if (!ignore) {
          if ((err as { status?: number })?.status === 401 || (err as { status?: number })?.status === 403) {
            clearCachedBootstrapSnapshot();
            setBootstrapFreshness("live");
            queryClient.removeQueries({ queryKey: queryKeys.auth.all() });
            queryClient.removeQueries({ queryKey: queryKeys.autonomy.all() });
            queryClient.removeQueries({ queryKey: queryKeys.prebooking.all() });
          } else if (queryClient.getQueryData(queryKeys.prebooking.feed())) {
            setBootstrapFreshness("stale");
          }
          setError(err instanceof Error ? err.message : "Initial load failed");
        }
      } finally {
        if (!ignore) {
          setIsBootstrapping(false);
        }
      }
    }
    prime();
    return () => {
      ignore = true;
    };
  }, [hasFreshHydratedBootstrap, hasHydratedFeedAtMount, queryClient]);

  // Ref forwarded to the ListDetailSurface detail region.
  // Focus moves into it whenever a new item is selected, and returns to the
  // triggering card on close (callers wire the return via onCloseCard clearing ?selected=).
  const detailRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (selectedInquiryId && detailRef.current) {
      detailRef.current.scrollTo({ top: 0, left: 0, behavior: "auto" });
      detailRef.current.focus();
    }
  }, [selectedInquiryId]);

  // Escape clears in-flight edit state. Selection/detail closing is handled by
  // the ListDetailSurface primitive's onKeyDown (it calls onCloseDetail which
  // runs onCloseCard → updateUrl({ selected: "" })). The window listener here
  // keeps edit state in sync without duplicating the URL update.
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setEditingId(null);
        setEditDraft("");
        setActionError("");
        // NOTE: URL clear (selected: "") is intentionally omitted here.
        // ListDetailSurface's Escape handler does that via onCloseDetail
        // and stops propagation, so this handler only fires when Escape is
        // pressed outside the detail region (e.g. while focus is in the list).
        // Clearing edit state there is harmless and keeps things consistent.
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const operator = session?.operator;
  const autoEnabled = autonomy?.tenant?.auto_enabled ?? false;
  const threshold = autonomy?.tenant?.confidence_threshold ?? 0.95;
  const inquiries = feed?.items ?? [];
  const propertyOptions = feed?.properties ?? [];
  const hasHydratedFeed = Boolean(feed);
  const showQueueSkeleton = isBootstrapping && !hasHydratedFeed;
  const freshnessBadge =
    bootstrapFreshness === "cached"
      ? { tone: "warning" as const, label: "Refreshing cached queue…" }
      : bootstrapFreshness === "stale"
      ? { tone: "danger" as const, label: "Showing cached queue — refresh failed" }
      : null;

  useEffect(() => {
    const tenantId = session?.operator?.tenant_id || "";
    const operatorId = session?.operator?.id || "";
    if (!session || !tenantId || !operatorId || !autonomy || !feed) return;
    persistBootstrapSnapshot({
      session,
      autonomy,
      messageFeed: feed,
      tenantId,
      operatorId,
      cachedAt: Date.now(),
    });
  }, [autonomy, feed, session]);

  async function handleSend(item: MessageFeedItem) {
    setActionError("");
    setPendingAction({ id: item.id, kind: "send" });
    try {
      await approveInquiryMutation.mutateAsync(item.id);
      const idx = visibleItems.findIndex((entry) => entry.id === item.id);
      const next = idx >= 0 ? visibleItems[idx + 1] ?? visibleItems[idx - 1] ?? null : null;
      updateUrl({ selected: next ? next.id : "" }, { replace: true });
      await loadMessageFeed(queryClient, { force: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Send failed");
    } finally {
      setPendingAction(null);
    }
  }

  async function handleReject(item: MessageFeedItem) {
    setActionError("");
    setPendingAction({ id: item.id, kind: "reject" });
    try {
      await rejectInquiryMutation.mutateAsync(item.id);
      const idx = visibleItems.findIndex((entry) => entry.id === item.id);
      const next = idx >= 0 ? visibleItems[idx + 1] ?? visibleItems[idx - 1] ?? null : null;
      updateUrl({ selected: next ? next.id : "" }, { replace: true });
      await loadMessageFeed(queryClient, { force: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Reject failed");
    } finally {
      setPendingAction(null);
    }
  }

  function handleStartEdit(item: MessageFeedItem) {
    setActionError("");
    setEditingId(item.id);
    setEditDraft(item.draftText || "");
  }

  function handleCancelEdit() {
    setEditingId(null);
    setEditDraft("");
    setActionError("");
  }

  async function loadBindingSuggestions(item: MessageFeedItem, query: string) {
    const trimmed = query.trim();
    setBindingDraftId(item.id);
    setBindingQuery(query);
    if (!trimmed) {
      setBindingSuggestions([]);
      setBindingError("");
      return;
    }
    setBindingLoading(true);
    setBindingError("");
    try {
      const payload = await suggestPropertyLinks(trimmed, 6);
      setBindingSuggestions(Array.isArray(payload.matches) ? payload.matches : []);
    } catch (err) {
      setBindingSuggestions([]);
      setBindingError(err instanceof Error ? err.message : "Property lookup failed");
    } finally {
      setBindingLoading(false);
    }
  }

  async function handleBindProperty(
    item: MessageFeedItem,
    suggestion: PropertyMatchSuggestion,
  ) {
    const propertyCode = (suggestion.property_code || "").trim();
    if (!propertyCode) {
      setBindingError("Missing property code");
      return;
    }
    setActionError("");
    setBindingError("");
    setPendingAction({ id: item.id, kind: "bind" });
    try {
      const primaryCandidate = (item.propertyBindingCandidates || []).find((entry) => entry.value);
      const result = await bindInquiryPropertyMutation.mutateAsync({
        id: item.id,
        body: {
          property_code: propertyCode,
          selected_candidate_value: primaryCandidate?.value || suggestion.matched_value || "",
          selected_candidate_type: primaryCandidate?.candidateType || suggestion.matched_on || "",
          search_query: bindingQuery.trim(),
        },
      });
      if (result.regenerated === false && result.regenerate_error) {
        setBindingError(`Property bound, but draft refresh failed: ${result.regenerate_error}`);
      }
      setBindingSuggestions([]);
      setBindingDraftId(null);
      setBindingQuery("");
      await loadMessageFeed(queryClient, { force: true });
      updateUrl({ selected: "" }, { replace: true });
    } catch (err) {
      setBindingError(err instanceof Error ? err.message : "Property bind failed");
    } finally {
      setPendingAction(null);
    }
  }

  async function handleSaveEdit(item: MessageFeedItem) {
    if (!editDraft.trim()) {
      setActionError("Reply text cannot be empty");
      return;
    }
    setActionError("");
    setPendingAction({ id: item.id, kind: "edit" });
    try {
      await editInquiryMutation.mutateAsync({ id: item.id, replyText: editDraft });
      const idx = visibleItems.findIndex((entry) => entry.id === item.id);
      const next = idx >= 0 ? visibleItems[idx + 1] ?? visibleItems[idx - 1] ?? null : null;
      setEditingId(null);
      setEditDraft("");
      updateUrl({ selected: next ? next.id : "" }, { replace: true });
      await loadMessageFeed(queryClient, { force: true });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Edit failed");
    } finally {
      setPendingAction(null);
    }
  }

  async function handleSaveAutonomy(next: { auto_enabled: boolean; confidence_threshold: number }) {
    const payload = await saveAutonomyMutation.mutateAsync(next);
    queryClient.setQueryData(queryKeys.autonomy.current(), payload);
  }

  // Shared filter-reset used by both the assurance-band ledger and the queue
  // tabs. Clears search/property/scope and jumps to the target tab+focus so a
  // filter click always lands on a clean, predictable view.
  function handleResetToMetric(next: { tab: QueueTab; focus: QueueMetricFocus }) {
    updateUrl({
      tab: next.tab,
      property: "",
      q: "",
      scope: "all",
      focus: next.focus,
      selected: "",
    });
  }

  const operatorId = operator?.id || "";
  const {
    queueByTab,
    searchedItems,
    visibleItems,
    tabCounts,
    awaitingCount,
    draftReadyCount,
    unboundCount,
    knowledgeGapCount,
    selectedInquiry,
    oldestAction,
    cards,
  } = useMemo(
    () =>
      buildQueueViewModel({
        activeTab,
        bindingDraftId,
        bindingError,
        bindingLoading,
        bindingQuery,
        bindingSuggestions,
        canOperatorSend,
        focusMetric,
        getConfidenceLabel,
        getNextStepGuidance,
        getQueueBucket,
        getRowState,
        inquiries,
        matchesMetricFocus,
        needsKnowledgeGap,
        operatorId,
        pendingAction,
        propertyId,
        queueDepth,
        scope,
        search: deferredSearch,
        selectedInquiryId,
        threshold,
      }),
    [
      activeTab,
      bindingDraftId,
      bindingError,
      bindingLoading,
      bindingQuery,
      bindingSuggestions,
      deferredSearch,
      focusMetric,
      inquiries,
      operatorId,
      pendingAction,
      propertyId,
      queueDepth,
      scope,
      selectedInquiryId,
      threshold,
    ],
  );

  // Keyboard navigation: j/k through the visible queue, Escape to close.
  // itemIds is memoized — hook reads latest state via stableRef, not deps.
  const visibleItemIds = useMemo(() => visibleItems.map((item) => item.id), [visibleItems]);
  useListKeyboardNav({
    itemIds: visibleItemIds,
    selectedId: selectedInquiryId ?? "",
    onSelect: (id) => updateUrl({ selected: id }, { replace: true }),
    onClose: () => updateUrl({ selected: "" }, { replace: true }),
    enabled: !focusMode,
  });

  useEffect(() => {
    if (!selectedInquiry || selectedInquiry.propertyId) {
      setBindingDraftId(null);
      setBindingQuery("");
      setBindingSuggestions([]);
      setBindingError("");
      setBindingLoading(false);
      return;
    }
    const initialQuery = preferredBindingQuery(selectedInquiry);
    setBindingDraftId(selectedInquiry.id);
    setBindingQuery(initialQuery);
    setBindingSuggestions([]);
    setBindingError("");
    if (initialQuery) {
      void loadBindingSuggestions(selectedInquiry, initialQuery);
    }
  }, [selectedInquiry?.id, selectedInquiry?.propertyId]);

  const momentumLine = autoEnabled
    ? `Oldest ${formatAge(oldestAction?.occurredAt)} · ${queueByTab.sent.length} replies visible`
    : `${propertyOptions.length} properties in scope · ${queueByTab.sent.length} replies visible`;

  const momentumPlaceholder = "Queue structure is loading.";

  return (
    <main className="grid grid-rows-[auto_auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full min-h-0 overflow-hidden">
        {focusMode ? null : (
          <SurfaceHeader
            title="Inquiry Operations"
            subtitle={hasHydratedFeed ? momentumLine : momentumPlaceholder}
            summaryLine={hasHydratedFeed
              ? (() => {
                  const needsReview = dashboardSummary?.filtered?.counts?.needs_review ?? 0;
                  const base = `${awaitingCount} active · ${unboundCount} unbound`;
                  return needsReview > 0 ? `${base} · ${needsReview} needs review` : base;
                })()
              : undefined}
            actions={
            <div className="flex gap-3.5 self-start flex-wrap items-center">
              <PreBookingAutonomyPopover
                autoEnabled={autoEnabled}
                formatAge={formatAge}
                formatPercent={formatPercent}
                threshold={threshold}
                lastChangedAt={autonomy?.tenant?.last_changed_at}
                inquiries={inquiries}
                onSave={handleSaveAutonomy}
                thresholdAvailable={autonomy?.tenant?.confidence_threshold != null}
                wasHeldForReview={wasHeldForReview}
              />
            </div>
            }
          />
        )}

        {focusMode ? null : (
          <PreBookingAssuranceBand
            autoEnabled={autoEnabled}
            thresholdPct={
              autonomy?.tenant?.confidence_threshold != null
                ? Math.round(autonomy.tenant.confidence_threshold * 100)
                : null
            }
            activeCount={awaitingCount}
            draftReadyCount={draftReadyCount}
            unboundCount={unboundCount}
            heldCount={knowledgeGapCount}
            sentTodayCount={tabCounts.sent}
            needsReviewFiltered={dashboardSummary?.filtered?.counts?.needs_review ?? 0}
            draftSignals={dashboardSummary?.pre_booking.draft_signals}
            loading={!hasHydratedFeed}
            activeFilter={
              activeTab === "sent"
                ? "sent"
                : activeTab === "held" && focusMetric === "knowledge_gap"
                  ? "knowledge_gap"
                  : focusMetric === "draft_ready"
                    ? "draft_ready"
                    : focusMetric === "unbound"
                      ? "unbound"
                      : "all"
            }
            onFilter={(key) => {
              if (key === "sent") {
                handleResetToMetric({ tab: "sent", focus: "all" });
              } else if (key === "knowledge_gap") {
                handleResetToMetric({ tab: "held", focus: "knowledge_gap" });
              } else {
                handleResetToMetric({ tab: "action", focus: key });
              }
            }}
          />
        )}

        <PreBookingControls
          activeTab={activeTab}
          hasHydratedFeed={hasHydratedFeed}
          propertyId={propertyId}
          propertyOptions={propertyOptions}
          scope={scope}
          search={search}
          tabCounts={tabCounts}
          focusMode={focusMode}
          onToggleFocusMode={() => updateUrl({ zen: focusMode ? "0" : "1" })}
          onSearchChange={(value) => updateUrl({ q: value })}
          onPropertyChange={(value) => updateUrl({ property: value })}
          onScopeChange={(value) => updateUrl({ scope: value })}
          onTabChange={(key) => updateUrl({ tab: key, focus: "all", selected: "" })}
        />

        <PreBookingQueueShell
          actionError={actionError}
          activeTab={activeTab}
          error={error}
          focusMetric={focusMetric}
          freshnessBadge={freshnessBadge}
          hasHydratedFeed={hasHydratedFeed}
          queueDepth={queueDepth}
          focusMode={focusMode}
          searchedItemsCount={searchedItems.length}
          search={search}
          propertyId={propertyId}
          showQueueSkeleton={showQueueSkeleton}
          visibleItemsCount={visibleItems.length}
          cards={cards}
          formatAge={formatAge}
          formatBindingCandidateType={formatBindingCandidateType}
          formatPercent={formatPercent}
          formatPropertyScore={formatPropertyScore}
          getChannelLabel={getChannelLabel}
          getQueueLabel={getQueueLabel}
          getQueueSpineTone={getQueueSpineTone}
          getQueueTone={getQueueTone}
          editingId={editingId}
          editDraft={editDraft}
          operator={operator}
          pendingActionId={pendingAction?.id || null}
          bindingDraftId={bindingDraftId}
          detailRef={detailRef}
          onBindProperty={handleBindProperty}
          onBindingQueryChange={(itemId, query) => {
            setBindingDraftId(itemId);
            setBindingQuery(query);
          }}
          onCloseCard={() => {
            setEditingId(null);
            setEditDraft("");
            setActionError("");
            updateUrl({ selected: "" }, { replace: true });
          }}
          onDepthChange={(value) => updateUrl({ depth: value })}
          onFindBindingSuggestions={loadBindingSuggestions}
          onReject={handleReject}
          onSaveEdit={handleSaveEdit}
          onSelectCard={(itemId) => updateUrl({ selected: itemId }, { replace: true })}
          onSetEditDraft={setEditDraft}
          onStartEdit={handleStartEdit}
          onCancelEdit={handleCancelEdit}
          onSend={handleSend}
        />
      </main>
  );
}
