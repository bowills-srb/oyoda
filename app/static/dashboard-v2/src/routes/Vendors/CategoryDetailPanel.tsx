import { useMemo, useState } from "react";

import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import { Checkbox } from "../../components/ui/checkbox";
import {
  useCreateVendorMutation,
  useDeleteVendorMutation,
  useUpdateVendorMutation,
} from "../../domain/vendors/mutations";
import type { Vendor } from "../../domain/vendors/types";
import { laneOf, type CategoryCoverage } from "./vendors_coverage";

/**
 * CategoryDetailPanel — the working surface for one selected category.
 *
 * Lane-aware by design, because the two lanes are genuinely different things:
 *
 *   experience → a contact lookup the AI reads from. When a guest asks about a
 *     crib, chair rental, or chef, the AI finds the vendor here and hands over
 *     the contact. No routing policy, no SLA, no warranty. The editor is just
 *     name / phone / website / what-the-AI-says.
 *
 *   dispatch → maintenance coverage. The backend scoring engine routes using
 *     the operational signals (warranty/manufacturer/emergency/after-hours/
 *     SLA/backup), so this panel's job is to let the operator review and
 *     CORRECT those signals — not to hand-build a dispatch order. Priority is
 *     shown as a tiebreaker, not as "the order", because the engine weighs
 *     warranty and emergency fit above it.
 *
 * Set-once surface: review-first, calm, editing one click in. Not a daily
 * console.
 */

type DraftState = {
  name: string;
  phone: string;
  website: string;
  aiScript: string;
  internalNotes: string;
  priority: number;
  active: boolean;
  // dispatch-only signals
  warrantyCapable: boolean;
  emergencyCapable: boolean;
  afterHoursAvailable: boolean;
  responseSlaMinutes: number;
  backupRank: number;
  manufacturerTags: string;
  warrantyProviderTags: string;
};

function vendorToDraft(vendor: Vendor): DraftState {
  const m = vendor.operationalMetadata;
  return {
    name: vendor.name,
    phone: vendor.phone,
    website: vendor.website,
    aiScript: vendor.aiScript,
    internalNotes: vendor.internalNotes,
    priority: vendor.priority,
    active: vendor.active,
    warrantyCapable: m.warrantyCapable,
    emergencyCapable: m.emergencyCapable,
    afterHoursAvailable: m.afterHoursAvailable,
    responseSlaMinutes: m.responseSlaMinutes,
    backupRank: m.backupRank,
    manufacturerTags: m.manufacturerTags.join(", "),
    warrantyProviderTags: m.warrantyProviderTags.join(", "),
  };
}

const EMPTY_DRAFT: DraftState = {
  name: "",
  phone: "",
  website: "",
  aiScript: "",
  internalNotes: "",
  priority: 1,
  active: true,
  warrantyCapable: false,
  emergencyCapable: false,
  afterHoursAvailable: false,
  responseSlaMinutes: 0,
  backupRank: 0,
  manufacturerTags: "",
  warrantyProviderTags: "",
};

function splitTags(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean);
}

type Props = {
  coverage: CategoryCoverage;
  vendors: Vendor[];
  onError: (error: Error | null) => void;
};

export function CategoryDetailPanel({ coverage, vendors, onError }: Props) {
  const lane = laneOf(coverage.category.workflowGroup);
  const isDispatch = lane === "dispatch";

  const categoryVendors = useMemo(
    () =>
      vendors
        .filter((v) => v.categorySlug === coverage.category.slug)
        .sort((a, b) => a.priority - b.priority),
    [vendors, coverage.category.slug],
  );

  const [editingId, setEditingId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<DraftState>(EMPTY_DRAFT);

  const createMutation = useCreateVendorMutation();
  const updateMutation = useUpdateVendorMutation();
  const deleteMutation = useDeleteVendorMutation();
  const busy = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;

  function beginAdd() {
    setEditingId(null);
    setDraft(EMPTY_DRAFT);
    setAdding(true);
  }

  function beginEdit(vendor: Vendor) {
    setAdding(false);
    setEditingId(vendor.id);
    setDraft(vendorToDraft(vendor));
  }

  function cancel() {
    setAdding(false);
    setEditingId(null);
    setDraft(EMPTY_DRAFT);
  }

  function buildBody() {
    const base = {
      name: draft.name.trim(),
      category_slug: coverage.category.slug,
      phone: draft.phone.trim(),
      website: draft.website.trim(),
      ai_script: draft.aiScript.trim(),
      internal_notes: draft.internalNotes.trim(),
      priority: Number(draft.priority) || 1,
      apply_scope: "all",
      property_ids: [] as string[],
      active: draft.active,
    };
    if (!isDispatch) return base;
    // Dispatch vendors carry the routing signals the backend scoring engine
    // reads. The /app/api/vendors create+update handlers accept
    // operational_metadata and run it through normalize_metadata, so these
    // snake_case keys persist and feed dispatch ordering.
    return {
      ...base,
      operational_metadata: {
        manufacturer_tags: splitTags(draft.manufacturerTags),
        warranty_provider_tags: splitTags(draft.warrantyProviderTags),
        warranty_capable: draft.warrantyCapable,
        emergency_capable: draft.emergencyCapable,
        after_hours_available: draft.afterHoursAvailable,
        response_sla_minutes: Number(draft.responseSlaMinutes) || 0,
        backup_rank: Number(draft.backupRank) || 0,
      },
    };
  }

  async function handleCreate() {
    if (!draft.name.trim()) return;
    onError(null);
    try {
      await createMutation.mutateAsync(buildBody());
      cancel();
    } catch (e) {
      onError(e instanceof Error ? e : new Error("Failed to add vendor"));
    }
  }

  async function handleSave(vendorId: string) {
    onError(null);
    try {
      await updateMutation.mutateAsync({ vendorId, body: buildBody() });
      cancel();
    } catch (e) {
      onError(e instanceof Error ? e : new Error("Failed to update vendor"));
    }
  }

  async function handleDelete(vendorId: string) {
    onError(null);
    try {
      await deleteMutation.mutateAsync(vendorId);
      if (editingId === vendorId) cancel();
    } catch (e) {
      onError(e instanceof Error ? e : new Error("Failed to remove vendor"));
    }
  }

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="flex items-start justify-between gap-3 border-b border-hairline px-5 py-4">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.06em] text-tertiary">
            {isDispatch ? "Dispatch · maintenance" : "Experience · recreational"}
          </div>
          <h2 className="mt-0.5 flex items-center gap-2 text-lg font-medium text-primary">
            <span aria-hidden className="text-base leading-none">{coverage.category.icon}</span>
            {coverage.category.displayName}
          </h2>
        </div>
        {!adding && !editingId ? (
          <Button type="button" size="sm" onClick={beginAdd} disabled={busy}>
            Add {isDispatch ? "responder" : "vendor"}
          </Button>
        ) : null}
      </div>

      <p className="m-0 px-5 pt-4 text-[12.5px] leading-relaxed text-secondary">
        {isDispatch
          ? "When a guest reports this kind of issue, the AI uses these signals to decide who to notify first — warranty fit and emergency readiness weigh above priority. Keep the signals accurate so routing stays correct."
          : "When a guest asks about this, the AI shares the contact below. Add anyone you'd want guests pointed to."}
      </p>

      <div className="flex flex-col gap-2.5 px-5 py-4">
        {categoryVendors.length === 0 && !adding ? (
          <div className="rounded-2xl border border-dashed border-hairline px-5 py-8 text-center">
            <p className="m-0 text-sm text-secondary">
              {isDispatch ? "No responder set up." : "No vendor added yet."}
            </p>
            <p className="mx-auto mt-1 max-w-sm text-[12px] leading-relaxed text-tertiary">
              {isDispatch
                ? "Issues in this category route to you until you add one."
                : "Guests asking about this will be told it isn't available until you add a contact."}
            </p>
            <div className="mt-4">
              <Button type="button" size="sm" onClick={beginAdd}>
                Add {isDispatch ? "responder" : "vendor"}
              </Button>
            </div>
          </div>
        ) : null}

        {categoryVendors.map((vendor, index) =>
          editingId === vendor.id ? (
            <VendorEditor
              key={vendor.id}
              draft={draft}
              setDraft={setDraft}
              isDispatch={isDispatch}
              busy={busy}
              onSave={() => void handleSave(vendor.id)}
              onCancel={cancel}
            />
          ) : (
            <VendorCard
              key={vendor.id}
              vendor={vendor}
              rank={index + 1}
              isDispatch={isDispatch}
              busy={busy}
              onEdit={() => beginEdit(vendor)}
              onDelete={() => void handleDelete(vendor.id)}
            />
          ),
        )}

        {adding ? (
          <VendorEditor
            draft={draft}
            setDraft={setDraft}
            isDispatch={isDispatch}
            busy={busy}
            onSave={() => void handleCreate()}
            onCancel={cancel}
          />
        ) : null}
      </div>
    </div>
  );
}

function Signal({ on, label }: { on: boolean; label: string }) {
  return (
    <span
      className={
        on
          ? "rounded-md bg-[var(--success-fill)] px-2 py-0.5 text-[11px] text-[var(--success-text)]"
          : "rounded-md border border-hairline px-2 py-0.5 text-[11px] text-tertiary"
      }
    >
      {label}
    </span>
  );
}

function VendorCard({
  vendor,
  rank,
  isDispatch,
  busy,
  onEdit,
  onDelete,
}: {
  vendor: Vendor;
  rank: number;
  isDispatch: boolean;
  busy: boolean;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const m = vendor.operationalMetadata;
  return (
    <article className="rounded-2xl border border-hairline bg-raised px-4 py-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          {isDispatch ? (
            <span className="mt-0.5 flex h-7 w-7 flex-none items-center justify-center rounded-md bg-sunken text-[12px] font-medium text-secondary tabular-nums">
              {rank}
            </span>
          ) : null}
          <div className="min-w-0">
            <div className="text-sm font-medium text-primary">{vendor.name}</div>
            <div className="mt-0.5 text-[12px] text-secondary">
              {[vendor.phone, vendor.website].filter(Boolean).join(" · ") || "No contact details"}
            </div>
          </div>
        </div>
        <div className="flex flex-none gap-1.5">
          <Button type="button" variant="secondary" size="sm" onClick={onEdit} disabled={busy}>
            Edit
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onDelete} disabled={busy}>
            Remove
          </Button>
        </div>
      </div>

      {vendor.aiScript ? (
        <p className="mt-2.5 rounded-lg bg-sunken px-3 py-2 text-[12px] leading-relaxed text-secondary">
          <span className="text-tertiary">AI says: </span>
          {vendor.aiScript}
        </p>
      ) : null}

      {isDispatch ? (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          <Signal on={m.warrantyCapable} label="Warranty-safe" />
          <Signal on={m.emergencyCapable} label="Emergency" />
          <Signal on={m.afterHoursAvailable} label="After-hours" />
          {m.responseSlaMinutes ? (
            <span className="rounded-md border border-hairline px-2 py-0.5 text-[11px] text-secondary tabular-nums">
              ~{m.responseSlaMinutes}m SLA
            </span>
          ) : null}
          {m.backupRank > 1 ? (
            <span className="rounded-md border border-hairline px-2 py-0.5 text-[11px] text-secondary tabular-nums">
              Backup tier {m.backupRank}
            </span>
          ) : null}
          {m.manufacturerTags.length ? (
            <span className="rounded-md border border-hairline px-2 py-0.5 text-[11px] text-secondary">
              {m.manufacturerTags.join(", ")}
            </span>
          ) : null}
        </div>
      ) : null}
    </article>
  );
}

function VendorEditor({
  draft,
  setDraft,
  isDispatch,
  busy,
  onSave,
  onCancel,
}: {
  draft: DraftState;
  setDraft: React.Dispatch<React.SetStateAction<DraftState>>;
  isDispatch: boolean;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const set = <K extends keyof DraftState>(key: K, value: DraftState[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  return (
    <article className="rounded-2xl border border-accent bg-raised px-4 py-4">
      <div className="grid gap-3">
        <label className="grid gap-1">
          <span className="text-[12px] text-secondary">Name</span>
          <Input value={draft.name} onChange={(e) => set("name", e.target.value)} placeholder="Vendor or company name" />
        </label>
        <div className="grid grid-cols-2 gap-3">
          <label className="grid gap-1">
            <span className="text-[12px] text-secondary">Phone</span>
            <Input value={draft.phone} onChange={(e) => set("phone", e.target.value)} />
          </label>
          <label className="grid gap-1">
            <span className="text-[12px] text-secondary">Website</span>
            <Input value={draft.website} onChange={(e) => set("website", e.target.value)} />
          </label>
        </div>
        <label className="grid gap-1">
          <span className="text-[12px] text-secondary">What the AI tells guests</span>
          <Textarea
            rows={2}
            value={draft.aiScript}
            onChange={(e) => set("aiScript", e.target.value)}
            placeholder={isDispatch ? "Context for routing this issue." : "e.g. Beachside Rentals delivers chairs and umbrellas — call or book online."}
          />
        </label>

        {isDispatch ? (
          <>
            <div className="grid grid-cols-2 gap-3">
              <label className="grid gap-1">
                <span className="text-[12px] text-secondary">Priority (tiebreaker)</span>
                <Input
                  type="number"
                  min={1}
                  value={draft.priority}
                  onChange={(e) => set("priority", Number(e.target.value) || 1)}
                />
              </label>
              <label className="grid gap-1">
                <span className="text-[12px] text-secondary">Response SLA (min)</span>
                <Input
                  type="number"
                  min={0}
                  value={draft.responseSlaMinutes}
                  onChange={(e) => set("responseSlaMinutes", Number(e.target.value) || 0)}
                />
              </label>
            </div>
            <label className="grid gap-1">
              <span className="text-[12px] text-secondary">Manufacturer / system tags</span>
              <Input
                value={draft.manufacturerTags}
                onChange={(e) => set("manufacturerTags", e.target.value)}
                placeholder="carrier, trane (comma-separated)"
              />
            </label>
            <label className="grid gap-1">
              <span className="text-[12px] text-secondary">Warranty provider tags</span>
              <Input
                value={draft.warrantyProviderTags}
                onChange={(e) => set("warrantyProviderTags", e.target.value)}
                placeholder="carrier (comma-separated)"
              />
            </label>
            <div className="flex flex-wrap gap-4 pt-1">
              <label className="flex items-center gap-2 text-[13px] text-secondary">
                <Checkbox checked={draft.warrantyCapable} onChange={(e) => set("warrantyCapable", e.target.checked)} />
                Warranty-safe
              </label>
              <label className="flex items-center gap-2 text-[13px] text-secondary">
                <Checkbox checked={draft.emergencyCapable} onChange={(e) => set("emergencyCapable", e.target.checked)} />
                Emergency-capable
              </label>
              <label className="flex items-center gap-2 text-[13px] text-secondary">
                <Checkbox checked={draft.afterHoursAvailable} onChange={(e) => set("afterHoursAvailable", e.target.checked)} />
                After-hours
              </label>
            </div>
            <p className="m-0 text-[11.5px] leading-relaxed text-tertiary">
              Manufacturer and warranty tags feed the routing engine — note that the operator is
              notified to handle dispatch until full automation is enabled.
            </p>
          </>
        ) : (
          <label className="flex items-center gap-2 pt-1 text-[13px] text-secondary">
            <Checkbox checked={draft.active} onChange={(e) => set("active", e.target.checked)} />
            Available to guests
          </label>
        )}

        <div className="flex gap-2 pt-1">
          <Button type="button" size="sm" onClick={onSave} disabled={busy || !draft.name.trim()}>
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        </div>
      </div>
    </article>
  );
}
