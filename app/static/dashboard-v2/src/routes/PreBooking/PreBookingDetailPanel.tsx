/**
 * PreBookingDetailPanel — Pre-Booking adapter for ReviewDrawer.
 *
 * Maps the Pre-Booking domain view-model into ReviewDrawer's named regions.
 * Behavior (send/edit/reject/bind) is unchanged from 770dd65.
 */

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { ReviewDrawer } from "../../components/system/ReviewDrawer/ReviewDrawer";
import type { SessionPayload } from "../../domain/auth/types";
import type {
  MessageFeedItem,
  MessageFeedPropertyBindingCandidate,
  PropertyMatchSuggestion,
} from "../../domain/prebooking/types";
import { getDraftHoldInsight } from "./holdReason";

type Guidance = {
  tone: "accent" | "warning" | "danger" | "default";
  title: string;
  body: string;
};

type PreBookingDetailPanelProps = {
  actionError: string;
  actionable: boolean;
  bindingCandidates: MessageFeedPropertyBindingCandidate[];
  bindingDraftId: string | null;
  bindingErrorForItem: string;
  bindingLoadingForItem: boolean;
  bindingQueryForItem: string;
  bindingSuggestionsForItem: PropertyMatchSuggestion[];
  draftText: string;
  editDraft: string;
  editingId: string | null;
  formatBindingCandidateType: (candidateType: string) => string;
  formatPercent: (value: number) => string;
  formatPropertyScore: (value?: number) => string;
  guestText: string;
  guidance: Guidance;
  isPending: boolean;
  isPendingBind: boolean;
  isPendingReject: boolean;
  isPendingSend: boolean;
  item: MessageFeedItem;
  needsKb: boolean;
  operator?: SessionPayload["operator"];
  pendingActionId: string | null;
  sendAllowed: boolean;
  onBindProperty: (item: MessageFeedItem, suggestion: PropertyMatchSuggestion) => void | Promise<void>;
  onBindingQueryChange: (itemId: string, query: string) => void;
  onClose: () => void;
  onFindBindingSuggestions: (item: MessageFeedItem, query: string) => void | Promise<void>;
  onReject: (item: MessageFeedItem) => void | Promise<void>;
  onSaveEdit: (item: MessageFeedItem) => void | Promise<void>;
  onSetEditDraft: (value: string) => void;
  onStartEdit: (item: MessageFeedItem) => void;
  onCancelEdit: () => void;
  onSend: (item: MessageFeedItem) => void | Promise<void>;
};

function candidateLabel(
  candidate: MessageFeedPropertyBindingCandidate,
  formatBindingCandidateType: (candidateType: string) => string,
) {
  if (candidate.candidateType === "raw_property_mention" && candidate.value.startsWith("/")) {
    return "Website path";
  }
  return formatBindingCandidateType(candidate.candidateType);
}

function uniqueEvidenceCandidates(
  item: MessageFeedItem,
  bindingCandidates: MessageFeedPropertyBindingCandidate[],
) {
  const merged = [...bindingCandidates];
  if (item.platformListingId && !merged.some((candidate) => candidate.candidateType === "platform_listing_id")) {
    merged.unshift({
      candidateType: "platform_listing_id",
      value: item.platformListingId,
      confidence: 0.98,
      source: "parser",
    });
  }
  if (item.platformUnitId && !merged.some((candidate) => candidate.candidateType === "platform_unit_id")) {
    merged.unshift({
      candidateType: "platform_unit_id",
      value: item.platformUnitId,
      confidence: 0.97,
      source: "parser",
    });
  }
  const seen = new Set<string>();
  return merged.filter((candidate) => {
    const key = `${candidate.candidateType}:${candidate.value}`.toLowerCase();
    if (!candidate.value || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function PreBookingDetailPanel({
  actionError,
  actionable,
  bindingCandidates,
  bindingDraftId,
  bindingErrorForItem,
  bindingLoadingForItem,
  bindingQueryForItem,
  bindingSuggestionsForItem,
  draftText,
  editDraft,
  editingId,
  formatBindingCandidateType,
  formatPercent,
  formatPropertyScore,
  guestText,
  guidance,
  isPending,
  isPendingBind,
  isPendingReject,
  isPendingSend,
  item,
  needsKb,
  operator,
  pendingActionId,
  sendAllowed,
  onBindProperty,
  onBindingQueryChange,
  onClose,
  onFindBindingSuggestions,
  onReject,
  onSaveEdit,
  onSetEditDraft,
  onStartEdit,
  onCancelEdit,
  onSend,
}: PreBookingDetailPanelProps) {
  const evidenceCandidates = uniqueEvidenceCandidates(item, bindingCandidates).slice(0, 6);
  const holdInsight = !draftText.trim() ? getDraftHoldInsight(item) : null;
  const parserFacts = [
    { label: "Source", value: item.sourceProvider || item.channel || "email" },
    { label: "Parser", value: item.parserSource || "unknown" },
    { label: "Route", value: item.routeOutcome || "pending bind" },
    { label: "Match type", value: item.propertyMatchType || "unresolved" },
  ].filter((entry) => entry.value);

  // --- blockerResolution region ---
  const blockerResolution =
    !item.propertyId ? (
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold text-primary">Binding evidence</span>
            <span className="text-xs text-tertiary">
              Everything the parser and canonical binder already found for this inquiry.
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {parserFacts.map((fact) => (
              <div key={fact.label} className="rounded-md bg-hover px-3 py-2">
                <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-tertiary">
                  {fact.label}
                </div>
                <div className="mt-1 text-sm text-primary">{fact.value}</div>
              </div>
            ))}
          </div>
          {evidenceCandidates.length ? (
            <div className="flex flex-col gap-2">
              <span className="text-xs font-semibold uppercase tracking-[0.16em] text-tertiary">
                Parsed property clues
              </span>
              <div className="flex flex-col gap-2">
                {evidenceCandidates.map((candidate, index) => (
                  <div
                    key={`${candidate.candidateType}:${candidate.value}:${index}`}
                    className="flex items-start justify-between gap-3 rounded-md border border-hairline px-3 py-2"
                  >
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <span className="text-xs font-semibold text-secondary">
                        {candidateLabel(candidate, formatBindingCandidateType)}
                      </span>
                      <span className="break-words text-sm text-primary">{candidate.value}</span>
                    </div>
                    <div className="flex flex-shrink-0 flex-col items-end gap-0.5 text-xs text-tertiary tabular-nums">
                      <span>{Math.round(Math.max(0, Math.min(1, candidate.confidence)) * 100)}%</span>
                      <span>{candidate.source || "inbound"}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-tertiary">
              No structured property clues survived parsing. Use the guest message below and search manually.
            </p>
          )}
          <p className="text-xs text-tertiary">
            Bind from this evidence directly here. The operator should not need to open Vrbo, the website, or
            another system just to identify the property.
          </p>
        </div>

        {bindingCandidates.length ? (
          <div className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
            <div className="flex flex-col gap-0.5">
              <span className="text-sm font-semibold text-primary">Likely property matches</span>
              <span className="text-xs text-tertiary">From the inbound parser and canonical binder</span>
            </div>
            <div className="flex flex-col gap-2">
              {bindingCandidates.map((candidate, index) => (
                <div
                  key={`${candidate.candidateType}:${candidate.value}:${index}`}
                  className="flex items-center justify-between gap-3 rounded-md bg-hover px-3 py-2"
                >
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-xs font-semibold text-secondary">
                      {formatBindingCandidateType(candidate.candidateType)}
                    </span>
                    <span className="truncate text-sm text-primary">{candidate.value}</span>
                  </div>
                  <div className="flex flex-shrink-0 flex-col items-end gap-0.5 text-xs text-tertiary tabular-nums">
                    <span>{Math.round(Math.max(0, Math.min(1, candidate.confidence)) * 100)}%</span>
                    <span>{candidate.source || "inbound"}</span>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-tertiary">
              These candidates come from the live parser and binder. Choose a property below to bind this
              inquiry and refresh the draft.
            </p>
          </div>
        ) : null}

        <div className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold text-primary">Bind to property</span>
            <span className="text-xs text-tertiary">
              Search canonical properties, then refresh this draft in place.
            </span>
          </div>
          <div className="flex gap-2">
            <Input
              aria-label="Search property matches"
              className="flex-1"
              value={bindingQueryForItem}
              onChange={(event) => onBindingQueryChange(item.id, event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && bindingQueryForItem.trim() && !isPending) {
                  event.preventDefault();
                  void onFindBindingSuggestions(item, bindingQueryForItem);
                }
              }}
              placeholder="Search by property name, listing ID, or alias"
              disabled={isPending}
              autoFocus
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={isPending || !bindingQueryForItem.trim()}
              onClick={() => void onFindBindingSuggestions(item, bindingQueryForItem)}
            >
              {bindingLoadingForItem ? "Searching…" : "Find matches"}
            </Button>
          </div>
          {bindingErrorForItem ? (
            <p className="text-xs text-[var(--danger-600)]">{bindingErrorForItem}</p>
          ) : null}
          {bindingSuggestionsForItem.length ? (
            <div className="flex flex-col gap-2">
              {bindingSuggestionsForItem.map((suggestion) => (
                <div
                  key={`${suggestion.property_code}:${suggestion.matched_value || suggestion.property_name || ""}`}
                  className="flex items-start justify-between gap-3 rounded-md border border-hairline px-3 py-2"
                >
                  <div className="flex min-w-0 flex-col gap-0.5">
                    <strong className="text-sm font-semibold text-primary">
                      {suggestion.property_name || suggestion.property_code || "Property"}
                    </strong>
                    <span className="text-xs text-secondary">
                      {(
                        suggestion.address_street ||
                        suggestion.community ||
                        suggestion.external_id ||
                        ""
                      ).trim() ||
                        suggestion.property_code ||
                        ""}
                    </span>
                    <span className="text-xs text-tertiary">
                      {formatPropertyScore(suggestion.score)} · matched on{" "}
                      {suggestion.matched_on || "property data"}
                    </span>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    className="flex-shrink-0"
                    disabled={isPending}
                    onClick={() => void onBindProperty(item, suggestion)}
                  >
                    {isPendingBind ? "Binding…" : "Bind & refresh draft"}
                  </Button>
                </div>
              ))}
            </div>
          ) : bindingDraftId === item.id && bindingQueryForItem.trim() && !bindingLoadingForItem ? (
            <p className="text-xs text-tertiary">
              No property matches yet. Try a different alias, listing ID, or property name.
            </p>
          ) : null}
        </div>
      </div>
    ) : undefined;

  // --- proposedAction body ---
  const proposedActionBody = editingId === item.id ? (
    <Textarea
      value={editDraft}
      onChange={(event) => onSetEditDraft(event.target.value)}
      rows={6}
      aria-label="Edit AI draft"
      autoFocus
      disabled={isPending}
    />
  ) : needsKb ? (
    <p className="text-sm text-tertiary">
      No draft generated — this inquiry is blocked on missing knowledge.
      {item.blockedByGapTopics?.length
        ? ` Missing: ${item.blockedByGapTopics.join(", ")}.`
        : ""}
    </p>
  ) : draftText ? (
    <p className="text-sm text-primary">{draftText}</p>
  ) : holdInsight ? (
    <div className="flex flex-col gap-3">
      <div className="rounded-md border border-hairline px-3 py-2.5">
        <div className="text-[12px] font-semibold text-primary">{holdInsight.summary}</div>
        {holdInsight.detail ? (
          <p className="mt-1 text-sm text-secondary">{holdInsight.detail}</p>
        ) : null}
      </div>
      {holdInsight.originalDraftPreview ? (
        <div className="rounded-md border border-hairline bg-hover px-3 py-2.5">
          <div className="font-mono text-[10px] font-medium uppercase tracking-[0.12em] text-tertiary">
            Generated draft before hold
          </div>
          <p className="mt-1 text-sm text-primary">{holdInsight.originalDraftPreview}</p>
        </div>
      ) : null}
    </div>
  ) : (
    <p className="text-sm text-tertiary">No draft generated yet.</p>
  );

  // --- decisionBar region ---
  const decisionBar = actionable && !needsKb && draftText.trim() ? (
    <>
      {editingId === item.id ? (
        <>
          <Button
            type="button"
            size="sm"
            disabled={isPending || !editDraft.trim()}
            onClick={() => void onSaveEdit(item)}
          >
            {pendingActionId === item.id ? "Sending…" : "Save & send"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={isPending}
            onClick={onCancelEdit}
          >
            Cancel
          </Button>
        </>
      ) : (
        <>
          <Button
            type="button"
            size="sm"
            disabled={!sendAllowed || isPending}
            onClick={() => void onSend(item)}
            title={
              sendAllowed
                ? "Send the AI draft to the guest"
                : "This draft needs operator review before it can be sent"
            }
          >
            {isPendingSend ? "Sending…" : "Send draft"}
          </Button>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            disabled={isPending}
            onClick={() => onStartEdit(item)}
          >
            Edit
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={isPending}
            onClick={() => void onReject(item)}
          >
            {isPendingReject ? "Rejecting…" : "Reject"}
          </Button>
        </>
      )}
      {actionError && pendingActionId === item.id ? (
        <span className="text-xs text-[var(--danger-600)]">{actionError}</span>
      ) : null}
    </>
  ) : actionable && !needsKb && !draftText.trim() ? (
    <>
      <span className="text-xs text-tertiary">
        No send-ready draft is stored for this inquiry. Review the hold reason above before acting.
      </span>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        disabled={isPending}
        onClick={() => void onReject(item)}
      >
        {isPendingReject ? "Rejecting…" : "Reject"}
      </Button>
    </>
  ) : needsKb ? (
    <>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        disabled
        title="Knowledge resolution is coming in v2"
      >
        Resolve in KB
      </Button>
      <span className="text-xs text-tertiary">Knowledge resolution is coming in v2.</span>
    </>
  ) : undefined;

  return (
    <ReviewDrawer
      onClose={onClose}
      summary={guidance}
      headerTitle={item.guestName || "Guest"}
      headerMeta={
        item.propertyId
          ? item.propertyName || "Bound property"
          : "Unbound · needs a property"
      }
      blockerResolution={blockerResolution}
      context={{ label: "Guest message", body: guestText || "(no guest message captured)" }}
      proposedAction={{
        label: draftText.trim() ? "AI draft" : "Draft status",
        confidence: item.confidence ?? undefined,
        body: proposedActionBody,
      }}
      decisionBar={decisionBar}
      attribution={operator?.name ? { name: operator.name, email: operator.email } : undefined}
    />
  );
}
