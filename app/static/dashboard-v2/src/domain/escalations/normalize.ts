/**
 * Defensive normalization for the escalations list payload.
 * Coerces nulls and unexpected shapes so the UI never crashes on bad data.
 */
import type {
  EscalationListItem,
  EscalationWorkflow,
  EscalationsPayload,
} from "./types";

function normalizeWorkflow(raw: unknown): EscalationWorkflow {
  const w = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  return {
    stage:              (w.stage as EscalationWorkflow["stage"]) ?? "detected",
    owner_state:        (w.owner_state as EscalationWorkflow["owner_state"]) ?? "unassigned",
    watcher_state:      (w.watcher_state as EscalationWorkflow["watcher_state"]) ?? "none",
    vendor_state:       typeof w.vendor_state === "string" ? w.vendor_state : "not_started",
    guest_update_state: typeof w.guest_update_state === "string" ? w.guest_update_state : "pending",
    priority:           (w.priority as EscalationWorkflow["priority"]) ?? null,
    reason:             typeof w.reason === "string" ? w.reason : null,
    summary:            typeof w.summary === "string" ? w.summary : null,
    assigned_to:        typeof w.assigned_to === "string" ? w.assigned_to : null,
    watcher_count:      typeof w.watcher_count === "number" ? w.watcher_count : 0,
    vendor: normalizeVendor(w.vendor),
    vendor_history:     Array.isArray(w.vendor_history) ? w.vendor_history : [],
    guest_update:       normalizeGuestUpdate(w.guest_update),
    sla:                normalizeSla(w.sla),
    timeline:           Array.isArray(w.timeline) ? w.timeline : [],
    work_orders:        normalizeWorkOrders(w.work_orders),
    actions:            Array.isArray(w.actions) ? w.actions : [],
    handoffs:           Array.isArray(w.handoffs) ? w.handoffs : [],
    detectors:          Array.isArray(w.detectors) ? w.detectors : [],
    refreshed_at:       typeof w.refreshed_at === "string" ? w.refreshed_at : null,
  };
}

function normalizeVendor(raw: unknown): EscalationWorkflow["vendor"] {
  const v = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  return {
    name:                 typeof v.name === "string" ? v.name : null,
    phone:                typeof v.phone === "string" ? v.phone : null,
    eta_minutes:          typeof v.eta_minutes === "number" ? v.eta_minutes : null,
    status:               typeof v.status === "string" ? v.status : "not_started",
    previous_vendor_name: typeof v.previous_vendor_name === "string" ? v.previous_vendor_name : null,
    replacement_count:    typeof v.replacement_count === "number" ? v.replacement_count : 0,
    last_transition_note: typeof v.last_transition_note === "string" ? v.last_transition_note : null,
    status_changed_at:    typeof v.status_changed_at === "string" ? v.status_changed_at : null,
    status_changed_by:    typeof v.status_changed_by === "string" ? v.status_changed_by : null,
  };
}

function normalizeGuestUpdate(raw: unknown): EscalationWorkflow["guest_update"] {
  const g = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  return {
    status:     typeof g.status === "string" ? g.status : "pending",
    due_at:     typeof g.due_at === "string" ? g.due_at : null,
    updated_at: typeof g.updated_at === "string" ? g.updated_at : null,
    note:       typeof g.note === "string" ? g.note : null,
  };
}

function normalizeSla(raw: unknown): EscalationWorkflow["sla"] {
  const s = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  return {
    acknowledged_at:  typeof s.acknowledged_at === "string" ? s.acknowledged_at : null,
    resolved_at:      typeof s.resolved_at === "string" ? s.resolved_at : null,
    ack_breached:     Boolean(s.ack_breached),
    resolve_breached: Boolean(s.resolve_breached),
  };
}

function normalizeWorkOrders(raw: unknown): EscalationWorkflow["work_orders"] {
  const w = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  return {
    open_count:  typeof w.open_count === "number" ? w.open_count : 0,
    total_count: typeof w.total_count === "number" ? w.total_count : 0,
    statuses:    Array.isArray(w.statuses) ? w.statuses : [],
    items:       Array.isArray(w.items) ? w.items : [],
  };
}

function normalizeItem(raw: Record<string, unknown>): EscalationListItem {
  return {
    ticket_id:          String(raw.ticket_id ?? ""),
    session_id:         typeof raw.session_id === "string" ? raw.session_id : null,
    session_token:      typeof raw.session_token === "string" ? raw.session_token : null,
    guest_name:         typeof raw.guest_name === "string" ? raw.guest_name : null,
    guest_phone:        typeof raw.guest_phone === "string" ? raw.guest_phone : null,
    guest_email:        typeof raw.guest_email === "string" ? raw.guest_email : null,
    property_name:      typeof raw.property_name === "string" ? raw.property_name : null,
    property_code:      typeof raw.property_code === "string" ? raw.property_code : null,
    reason:             typeof raw.reason === "string" ? raw.reason : null,
    priority:           (raw.priority as EscalationListItem["priority"]) ?? "medium",
    status:             typeof raw.status === "string" ? raw.status : "pending",
    summary:            typeof raw.summary === "string" ? raw.summary : null,
    last_message:       typeof raw.last_message === "string" ? raw.last_message : null,
    assigned_to:        typeof raw.assigned_to === "string" ? raw.assigned_to : null,
    resolution_notes:   typeof raw.resolution_notes === "string" ? raw.resolution_notes : null,
    watchers:           Array.isArray(raw.watchers) ? raw.watchers : [],
    vendor_name:        typeof raw.vendor_name === "string" ? raw.vendor_name : null,
    vendor_phone:       typeof raw.vendor_phone === "string" ? raw.vendor_phone : null,
    vendor_eta_minutes: typeof raw.vendor_eta_minutes === "number" ? raw.vendor_eta_minutes : null,
    vendor_status:      typeof raw.vendor_status === "string" ? raw.vendor_status : null,
    guest_updated_at:   typeof raw.guest_updated_at === "string" ? raw.guest_updated_at : null,
    guest_update_status: typeof raw.guest_update_status === "string" ? raw.guest_update_status : null,
    guest_update_due_at: typeof raw.guest_update_due_at === "string" ? raw.guest_update_due_at : null,
    guest_update_note:  typeof raw.guest_update_note === "string" ? raw.guest_update_note : null,
    acknowledged_at:    typeof raw.acknowledged_at === "string" ? raw.acknowledged_at : null,
    resolved_at:        typeof raw.resolved_at === "string" ? raw.resolved_at : null,
    created_at:         typeof raw.created_at === "string" ? raw.created_at : null,
    workflow:           normalizeWorkflow(raw.workflow),
  };
}

export function normalizeEscalationsPayload(raw: unknown): EscalationsPayload {
  const data = (typeof raw === "object" && raw !== null ? raw : {}) as Record<string, unknown>;
  const items = Array.isArray(data.escalations) ? data.escalations : [];
  const summary = (typeof data.summary === "object" && data.summary !== null
    ? data.summary
    : {}) as Record<string, unknown>;
  return {
    escalations: items.map((item) =>
      normalizeItem(typeof item === "object" && item !== null ? (item as Record<string, unknown>) : {}),
    ),
    count: typeof data.count === "number" ? data.count : items.length,
    summary: {
      pending:     typeof summary.pending === "number" ? summary.pending : 0,
      acknowledged: typeof summary.acknowledged === "number" ? summary.acknowledged : 0,
      resolved:    typeof summary.resolved === "number" ? summary.resolved : 0,
      open:        typeof summary.open === "number" ? summary.open : 0,
    },
  };
}
