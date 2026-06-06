/**
 * domain/escalations/types.ts
 *
 * Full types for the escalation domain. Replaces the thin Escalation row
 * from domain/today/types.ts — that type stays for Today's own usage, but
 * this module is the authoritative shape for the Escalations surface.
 *
 * Source of truth: escalation_workflow_service._build_workflow() (verified
 * against backend 2025-05). The list endpoint returns workflow inline on
 * each item — no separate per-ticket workflow fetch is needed.
 */

// ─── Workflow sub-types ────────────────────────────────────────────────────

export type WorkflowStage = "detected" | "triaged" | "vendor_dispatch" | "resolved";
export type OwnerState   = "unassigned" | "acknowledged" | "assigned";
export type WatcherState = "none" | "tracking" | "notified";
export type Priority     = "urgent" | "high" | "medium" | "low";

export type TimelineEntry = {
  key:   string;
  label: string;
  at:    string | null;
  done:  boolean;
};

export type VendorInfo = {
  name:               string | null;
  phone:              string | null;
  eta_minutes:        number | null;
  status:             string;
  previous_vendor_name: string | null;
  replacement_count:  number;
  last_transition_note: string | null;
  status_changed_at:  string | null;
  status_changed_by:  string | null;
};

export type VendorHistoryEntry = {
  changed_at:       string;
  changed_by:       string | null;
  vendor_name:      string | null;
  vendor_phone:     string | null;
  vendor_status:    string;
  vendor_eta_minutes: number | null;
  note?:            string;
};

export type GuestUpdate = {
  status:     string;
  due_at:     string | null;
  updated_at: string | null;
  note:       string | null;
};

export type SlaInfo = {
  acknowledged_at: string | null;
  resolved_at:     string | null;
  ack_breached:    boolean;
  resolve_breached: boolean;
};

export type WorkOrderSummary = {
  open_count:  number;
  total_count: number;
  statuses:    string[];
  items:       WorkOrderItem[];
};

export type WorkOrderItem = {
  id:          string;
  title:       string;
  status:      string;
  assigned_to: string | null;
  created_at:  string | null;
};

export type SuggestedAction = {
  type:        string;
  label:       string;
  description: string | null;
  draft_text:  string | null;
  enabled:     boolean;
};

export type Detector = {
  key:     string;
  label:   string;
  fired:   boolean;
  detail:  string | null;
};

export type Handoff = {
  id:           string;
  assignee_label: string | null;
  created_at:   string | null;
  note:         string | null;
  status:       string;
};

// ─── Core workflow shape (mirrors _build_workflow output) ──────────────────

export type EscalationWorkflow = {
  stage:             WorkflowStage;
  owner_state:       OwnerState;
  watcher_state:     WatcherState;
  vendor_state:      string;
  guest_update_state: string;
  priority:          Priority | null;
  reason:            string | null;
  summary:           string | null;
  assigned_to:       string | null;
  watcher_count:     number;
  vendor:            VendorInfo;
  vendor_history:    VendorHistoryEntry[];
  guest_update:      GuestUpdate;
  sla:               SlaInfo;
  timeline:          TimelineEntry[];
  work_orders:       WorkOrderSummary;
  actions:           SuggestedAction[];
  handoffs:          Handoff[];
  detectors:         Detector[];
  refreshed_at:      string | null;
};

// ─── List-item shape (flat fields + workflow inline) ──────────────────────

export type EscalationListItem = {
  ticket_id:         string;
  session_id:        string | null;
  session_token:     string | null;
  guest_name:        string | null;
  guest_phone:       string | null;
  guest_email:       string | null;
  property_name:     string | null;
  property_code:     string | null;
  reason:            string | null;
  priority:          Priority;
  status:            string;
  summary:           string | null;
  last_message:      string | null;
  assigned_to:       string | null;
  resolution_notes:  string | null;
  watchers:          string[];
  vendor_name:       string | null;
  vendor_phone:      string | null;
  vendor_eta_minutes: number | null;
  vendor_status:     string | null;
  guest_updated_at:  string | null;
  guest_update_status: string | null;
  guest_update_due_at: string | null;
  guest_update_note: string | null;
  acknowledged_at:   string | null;
  resolved_at:       string | null;
  created_at:        string | null;
  workflow:          EscalationWorkflow;
};

// ─── List response ─────────────────────────────────────────────────────────

export type EscalationSummary = {
  pending:     number;
  acknowledged: number;
  resolved:    number;
  open:        number;
};

export type EscalationsPayload = {
  escalations: EscalationListItem[];
  count:       number;
  summary:     EscalationSummary;
};

// ─── Mutation inputs ───────────────────────────────────────────────────────

export type AssignInput = {
  assigned_to: string;
};

export type ResolveInput = {
  notes?: string;
};

export type DispatchVendorInput = {
  vendor_name?:       string;
  vendor_phone?:      string;
  vendor_eta_minutes?: number;
  vendor_status:      string;
  replace_existing?:  boolean;
  guest_updated?:     boolean;
};

export type CoordinationInput = {
  watchers?:              string[];
  guest_update_note?:     string;
  mark_guest_updated?:    boolean;
  notify_watchers?:       boolean;
  guest_update_status?:   string;
  guest_update_due_at?:   string;
};
