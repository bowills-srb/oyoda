export type FilteredReason = "suppressed" | "non_guest" | "needs_review" | "system";

export type FilteredItem = {
  source_channel: string;
  source_message_id: string;
  route_outcome: string;
  reason: FilteredReason;
  sender_display_name: string;
  sender_address: string;
  raw_subject: string;
  preview: string;
  sent_at: string | null;
  selected_property_code: string;
  fallback_reason: string;
  promotable: boolean;
};

export type FilteredListPayload = {
  window: string;
  reason: string;
  total: number;
  counts: Partial<Record<FilteredReason, number>>;
  items: FilteredItem[];
};

export type PromoteResult = {
  ok: boolean;
  promoted: boolean;
  already_in_queue: boolean;
  draft_id: string;
  guest_thread_id: string | null;
  source_channel: string;
  source_message_id: string;
  status: string;
};
