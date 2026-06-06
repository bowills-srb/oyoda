/**
 * EscalationDetailPanel — ReviewDrawer adapter for escalations.
 *
 * Proves the ReviewDrawer optional-region contract:
 *   - NO confidence chip (proposedAction omitted entirely)
 *   - NO editable draft
 *   - summary.tone ← SLA breach → danger; high/urgent priority → warning; else default
 *   - blockerResolution ← stage-dependent forms (assign / dispatch / coordination)
 *   - decisionBar ← action buttons scoped to current workflow state
 *
 * Actions with no backing endpoint are rendered disabled with a "coming soon"
 * title — never broken/hidden.
 */
import { useState, type ReactNode } from "react";
import { ReviewDrawer } from "../../../components/system/ReviewDrawer/ReviewDrawer";
import { EscalationTimeline } from "./EscalationTimeline";
import { Button } from "../../../components/ui/button";
import { Input } from "../../../components/ui/input";
import { Textarea } from "../../../components/ui/textarea";
import {
  useAssignEscalation,
  useResolveEscalation,
  useDispatchVendor,
  useSaveCoordination,
} from "../../../domain/escalations/mutations";
import type { EscalationListItem } from "../../../domain/escalations/types";

type Props = {
  item: EscalationListItem;
  onClose: () => void;
};

function deriveTone(item: EscalationListItem): "danger" | "warning" | "default" {
  if (item.workflow.sla.ack_breached || item.workflow.sla.resolve_breached) return "danger";
  if (item.priority === "urgent" || item.priority === "high") return "warning";
  return "default";
}

function formatSlaNote(item: EscalationListItem): string {
  const { ack_breached, resolve_breached } = item.workflow.sla;
  if (ack_breached && resolve_breached) return " · Ack + resolve SLA breached";
  if (ack_breached) return " · Ack SLA breached";
  if (resolve_breached) return " · Resolve SLA breached";
  return "";
}

export function EscalationDetailPanel({ item, onClose }: Props) {
  const { workflow } = item;

  // ── Local form state ──────────────────────────────────────────────────────
  const [assignTo, setAssignTo] = useState(item.assigned_to ?? "");
  const [resolveNotes, setResolveNotes] = useState("");
  const [vendorName, setVendorName] = useState(workflow.vendor.name ?? "");
  const [vendorPhone, setVendorPhone] = useState(workflow.vendor.phone ?? "");
  const [vendorEta, setVendorEta] = useState<string>(
    workflow.vendor.eta_minutes != null ? String(workflow.vendor.eta_minutes) : "",
  );
  const [guestUpdateNote, setGuestUpdateNote] = useState(workflow.guest_update.note ?? "");

  // ── Mutations ─────────────────────────────────────────────────────────────
  const assignMutation = useAssignEscalation();
  const resolveMutation = useResolveEscalation();
  const dispatchMutation = useDispatchVendor();
  const coordinationMutation = useSaveCoordination();

  const isPending =
    assignMutation.isPending ||
    resolveMutation.isPending ||
    dispatchMutation.isPending ||
    coordinationMutation.isPending;

  // ── summary region ────────────────────────────────────────────────────────
  const tone = deriveTone(item);
  const slaNote = formatSlaNote(item);

  const summary = {
    tone,
    title: workflow.reason ?? item.reason ?? "Escalation",
    body:
      (workflow.summary ?? item.summary ?? "No details available.") +
      (slaNote ? `\n\n${slaNote.trim()}` : ""),
  };

  // ── context region ────────────────────────────────────────────────────────
  const contextLines = [
    item.guest_name ? `Guest: ${item.guest_name}` : null,
    item.property_name ? `Property: ${item.property_name}` : null,
    item.last_message ? `Last message: "${item.last_message}"` : null,
  ]
    .filter(Boolean)
    .join("\n");

  const context =
    contextLines
      ? { label: "Guest context", body: contextLines }
      : undefined;

  // ── blockerResolution region ──────────────────────────────────────────────
  let blockerResolution: ReactNode = null;

  if (workflow.owner_state === "unassigned") {
    blockerResolution = (
      <div className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold text-primary">Assign escalation</span>
          <span className="text-xs text-tertiary">
            No one is watching this yet. Assign it to an operator to track ownership.
          </span>
        </div>
        <div className="flex gap-2">
          <Input
            aria-label="Assign to (operator email or name)"
            placeholder="Operator email or name"
            value={assignTo}
            onChange={(e) => setAssignTo(e.target.value)}
            disabled={isPending}
            className="flex-1"
          />
          <Button
            type="button"
            size="sm"
            disabled={isPending || !assignTo.trim()}
            onClick={() =>
              assignMutation.mutate({
                ticketId: item.ticket_id,
                body: { assigned_to: assignTo.trim() },
              })
            }
          >
            {assignMutation.isPending ? "Assigning…" : "Assign"}
          </Button>
        </div>
        {assignMutation.isError ? (
          <p className="text-xs text-[var(--danger-600)]">Failed to assign. Please try again.</p>
        ) : null}
      </div>
    );
  } else if (
    workflow.stage === "vendor_dispatch" &&
    (workflow.vendor_state === "not_started" || workflow.vendor_state === "needed")
  ) {
    blockerResolution = (
      <div className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold text-primary">Dispatch vendor</span>
          <span className="text-xs text-tertiary">
            This escalation is in vendor dispatch stage. Record the vendor you're sending.
          </span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <Input
            aria-label="Vendor name"
            placeholder="Vendor name"
            value={vendorName}
            onChange={(e) => setVendorName(e.target.value)}
            disabled={isPending}
          />
          <Input
            aria-label="Vendor phone"
            placeholder="Phone number"
            value={vendorPhone}
            onChange={(e) => setVendorPhone(e.target.value)}
            disabled={isPending}
          />
          <Input
            aria-label="ETA in minutes"
            placeholder="ETA (minutes)"
            type="number"
            min={0}
            value={vendorEta}
            onChange={(e) => setVendorEta(e.target.value)}
            disabled={isPending}
          />
        </div>
        <Button
          type="button"
          size="sm"
          className="self-start"
          disabled={isPending || !vendorName.trim()}
          onClick={() =>
            dispatchMutation.mutate({
              ticketId: item.ticket_id,
              body: {
                vendor_name: vendorName.trim() || undefined,
                vendor_phone: vendorPhone.trim() || undefined,
                vendor_eta_minutes: vendorEta ? parseInt(vendorEta, 10) : undefined,
                vendor_status: "dispatched",
              },
            })
          }
        >
          {dispatchMutation.isPending ? "Dispatching…" : "Record dispatch"}
        </Button>
        {dispatchMutation.isError ? (
          <p className="text-xs text-[var(--danger-600)]">Failed to dispatch. Please try again.</p>
        ) : null}
      </div>
    );
  } else if (workflow.guest_update_state === "pending") {
    blockerResolution = (
      <div className="flex flex-col gap-3 rounded-lg border border-hairline p-4">
        <div className="flex flex-col gap-0.5">
          <span className="text-sm font-semibold text-primary">Send guest update</span>
          <span className="text-xs text-tertiary">
            The guest hasn't been updated yet. Add a coordination note and mark them updated.
          </span>
        </div>
        <Textarea
          aria-label="Guest update note"
          placeholder="What should the guest know right now?"
          rows={3}
          value={guestUpdateNote}
          onChange={(e) => setGuestUpdateNote(e.target.value)}
          disabled={isPending}
        />
        <Button
          type="button"
          size="sm"
          className="self-start"
          disabled={isPending || !guestUpdateNote.trim()}
          onClick={() =>
            coordinationMutation.mutate({
              ticketId: item.ticket_id,
              body: {
                guest_update_note: guestUpdateNote.trim(),
                mark_guest_updated: true,
              },
            })
          }
        >
          {coordinationMutation.isPending ? "Saving…" : "Mark guest updated"}
        </Button>
        {coordinationMutation.isError ? (
          <p className="text-xs text-[var(--danger-600)]">Failed to save. Please try again.</p>
        ) : null}
      </div>
    );
  }

  // ── decisionBar region ────────────────────────────────────────────────────
  const decisionBar = workflow.stage !== "resolved" ? (
    <>
      {/* Assign — only show if not yet assigned */}
      {workflow.owner_state !== "unassigned" && (
        <Button
          type="button"
          variant="secondary"
          size="sm"
          disabled={isPending || !assignTo.trim()}
          onClick={() =>
            assignMutation.mutate({
              ticketId: item.ticket_id,
              body: { assigned_to: assignTo.trim() },
            })
          }
          title="Reassign this escalation to another operator"
        >
          Reassign
        </Button>
      )}

      {/* Resolve */}
      <Button
        type="button"
        size="sm"
        disabled={isPending}
        onClick={() =>
          resolveMutation.mutate({
            ticketId: item.ticket_id,
            body: { notes: resolveNotes.trim() || undefined },
          })
        }
      >
        {resolveMutation.isPending ? "Resolving…" : "Resolve"}
      </Button>

      {/* Resolution notes inline input */}
      <Input
        aria-label="Resolution notes (optional)"
        placeholder="Resolution notes (optional)"
        value={resolveNotes}
        onChange={(e) => setResolveNotes(e.target.value)}
        disabled={isPending}
        className="h-8 flex-1 text-xs"
      />

      {resolveMutation.isError ? (
        <span className="w-full text-xs text-[var(--danger-600)]">
          Failed to resolve. Please try again.
        </span>
      ) : null}
    </>
  ) : (
    <span className="text-xs text-tertiary">Resolved · no further actions available.</span>
  );

  // ── attribution (none for escalations — no AI actor) ─────────────────────

  return (
    <div className="flex flex-col">
      {/* Timeline strip above the drawer content */}
      <div className="border-b border-hairline px-6 py-4">
        <EscalationTimeline timeline={workflow.timeline} currentStage={workflow.stage} />
      </div>

      <ReviewDrawer
        onClose={onClose}
        summary={summary}
        blockerResolution={blockerResolution}
        context={context}
        // proposedAction intentionally omitted — escalations have no AI draft
        decisionBar={decisionBar}
      />
    </div>
  );
}
