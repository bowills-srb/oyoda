/**
 * actionLabels — UI-facing metadata for each action_type in the
 * StayActionAgent queue.
 *
 * The backend's StayActionAgent enqueues actions with stable action_type
 * strings; each one maps to a human-readable label, a verb the button
 * should display, and a flag telling the UI whether the action carries a
 * pre-composed guest-facing message in its payload.
 *
 * action_type values are sourced from app/services/operator/stay_action_agent.py
 * (the ACTION_* constants). Keep this table in sync if the agent gains
 * new action types — an unknown type falls back to a snake-case-to-
 * Title-Case rendering rather than crashing, so the addition is
 * non-fatal, but the button copy will read awkwardly until labeled.
 *
 * The "sends a guest message" distinction matters for UX: those actions
 * should show a preview of payload.message_text before the operator
 * confirms, because clicking commits an outbound message to the guest.
 * Non-message actions (ops_review, owner_internal_update, etc.) only
 * affect internal state — a notification, a handoff, a work order — so
 * they don't need a preview affordance.
 */

export type ActionTypeLabel = {
  // Short label for the button itself.
  label: string;
  // One-line description of what the action will do, shown beneath the
  // label when the action surfaces in the expansion.
  description: string;
  // True when the action's execution sends a message to the guest via
  // channel_router. The UI shows a preview of payload.message_text and
  // labels the button "Send" rather than the action's verb.
  sendsGuestMessage: boolean;
};

const ACTION_LABELS: Record<string, ActionTypeLabel> = {
  // Message-sending actions. payload.message_text is composed by the brain
  // and sent verbatim when the operator confirms. The "Send" framing is
  // intentional — these aren't "open a thing", they're "deliver this".
  proactive_outreach: {
    label: "Send proactive update",
    description: "Send the AI-composed proactive touch to the guest.",
    sendsGuestMessage: true,
  },
  guest_status_response: {
    label: "Send status update",
    description: "Reply to the guest's most recent check-in with the AI-composed status.",
    sendsGuestMessage: true,
  },
  guest_eta_update: {
    label: "Send vendor ETA",
    description: "Tell the guest the current vendor ETA.",
    sendsGuestMessage: true,
  },

  // Internal-state actions. Click commits the orchestrated step (handoff,
  // notification, work order). The operator's verb is "open" or "log"
  // rather than "send" because nothing reaches the guest from this click.
  ops_review: {
    label: "Open ops review",
    description: "Flag this session for operator review and create a notification.",
    sendsGuestMessage: false,
  },
  knowledge_response: {
    label: "Log knowledge response",
    description: "Mark this guest question as a knowledge-base candidate.",
    sendsGuestMessage: false,
  },
  vendor_coordination: {
    label: "Open vendor coordination",
    description: "Open a work order with the recommended vendor; you can refine the assignment afterward.",
    sendsGuestMessage: false,
  },
  turnover_coordination: {
    label: "Open turnover coordination",
    description: "Start turnover coordination with the recommended cleaning vendor.",
    sendsGuestMessage: false,
  },
  post_checkout_walkthrough: {
    label: "Open walkthrough review",
    description: "Open a post-checkout documentation handoff.",
    sendsGuestMessage: false,
  },
  owner_internal_update: {
    label: "Send owner update",
    description: "Create an owner/internal handoff for this session.",
    sendsGuestMessage: false,
  },
  accounting_claim_handoff: {
    label: "Open accounting review",
    description: "Hand this session off to accounting/claims for billing follow-up.",
    sendsGuestMessage: false,
  },
};

export function labelForAction(actionType: string): ActionTypeLabel {
  if (ACTION_LABELS[actionType]) return ACTION_LABELS[actionType];
  // Fallback for action types we haven't labeled yet. Snake-case to
  // Title Case; assume internal-state (not message-sending) since we
  // don't know the action's behavior and the conservative default is
  // to not render a "Send" button that might surprise the operator.
  const title = actionType
    ? actionType
        .split("_")
        .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : part))
        .join(" ")
    : "Run action";
  return {
    label: title,
    description: "Run this action.",
    sendsGuestMessage: false,
  };
}
