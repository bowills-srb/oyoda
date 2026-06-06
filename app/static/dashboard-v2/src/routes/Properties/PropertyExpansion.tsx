import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { Badge } from "../../components/primitives/Badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { cn } from "../../lib/utils";
import {
  propertyGroupsQueryOptions,
  propertyMemberGroupsQueryOptions,
  useSetPropertyMemberGroupsMutation,
  useCreatePropertyGroupMutation,
} from "../../domain/knowledgeProposals";

import { StageRail } from "../../components/system/StageRail";
import { resolveStage, type DraftTrackRecord } from "../../domain/trainingArc/stageModel";
import { DocumentUploadForm } from "./DocumentUploadForm";
import {
  COMPLETENESS_TOOLTIP,
  formatCompletenessBreakdown,
} from "./completeness";
import { READINESS_LABELS } from "./readiness";
import type {
  CompletenessResult,
  DocumentType,
  DocumentUploadPreset,
  PropertyAsset,
  PropertyDocumentUploadResult,
  PropertyGap,
  PropertyKbEntry,
  PropertyRow,
} from "./types";

/**
 * PropertyExpansion — inline expansion content for a property row.
 * Reused both inline (row view) and inside the grid-view modal.
 */

function formatRelativeAge(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const diffMs = Date.now() - date.getTime();
  const diffMin = Math.floor(diffMs / (1000 * 60));
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 30) return `${diffD}d ago`;
  return date.toLocaleDateString();
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
}

function describeAutonomy(approvalMode: string, minConfidence: number): string {
  const pct = Math.round(minConfidence * 100);
  switch ((approvalMode || "").toLowerCase()) {
    case "auto":
      return `Auto-send replies when confidence ≥ ${pct}%`;
    case "required":
      return "Review every reply before sending";
    case "mixed":
      return `Mixed autonomy across lanes (${pct}% floor)`;
    default:
      return "Review every reply before sending";
  }
}

function suggestedDocumentTypeForGap(gap: PropertyGap): DocumentType {
  switch ((gap.categorySlug || "").toLowerCase()) {
    case "amenities":
      return "amenities";
    case "policies":
    case "policy":
      return "portfolio_policy";
    case "rental_agreement":
      return "rental_agreement";
    case "vendor_contacts":
    case "vendor_contact":
      return "misc";
    default:
      return "house_manual";
  }
}

function CompletenessChip({
  label,
  scorePct,
  displayLabel,
  title,
}: {
  label: "well-documented" | "has-gaps" | "bare-bones";
  scorePct: number;
  displayLabel: string;
  title: string;
}) {
  const tone = READINESS_LABELS[label].tone;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11.5px] font-semibold whitespace-nowrap",
        tone === "success" && "bg-[var(--success-fill)] text-[var(--success-text)]",
        tone === "warning" && "bg-[var(--warning-fill)] text-[var(--warning-text)]",
        tone === "danger" && "bg-[var(--danger-fill)] text-[var(--danger-text)]",
      )}
      title={title}
    >
      <span className="tabular-nums">{scorePct}%</span>
      <span className="font-medium text-[11px] opacity-85">{displayLabel}</span>
    </span>
  );
}

const SECTION_TITLE_CLS =
  "m-0 text-[13px] font-semibold text-primary uppercase tracking-[0.05em]";
const SECTION_COUNT_CLS = "text-[11.5px] text-tertiary tabular-nums";
const SECTION_EMPTY_CLS = "text-xs text-tertiary m-0 py-2";
const ENTRY_BASE_CLS =
  "p-2.5 px-3 rounded-lg bg-raised border border-hairline flex flex-col gap-1.5";
const ENTRY_HEAD_CLS = "flex items-start gap-2 flex-wrap";
const ENTRY_META_CLS = "text-[11px] text-tertiary tabular-nums";
const ENTRY_Q_CLS = "text-[13px] font-medium text-primary m-0 leading-[1.4]";
const ENTRY_BODY_CLS = "text-xs text-secondary m-0 leading-[1.5]";

/**
 * GroupMembershipEditor — sleek, collapsed-by-default control for correcting
 * which property groups a property belongs to. Shows current groups as chips
 * with a quiet "Edit" link; clicking reveals a compact checklist of the
 * tenant's groups. Writes property_group_memberships (the load-bearing table).
 *
 * Designed to be invisible until needed: no boxes unless the operator opts in.
 */
function GroupMembershipEditor({ propertyId }: { propertyId: string }) {
  const allGroupsQuery = useQuery(propertyGroupsQueryOptions());
  const memberQuery = useQuery(propertyMemberGroupsQueryOptions(propertyId));
  const setMutation = useSetPropertyMemberGroupsMutation();
  const createMutation = useCreatePropertyGroupMutation();

  const [editing, setEditing] = useState(false);
  const [draftIds, setDraftIds] = useState<string[] | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [creatingGroup, setCreatingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");

  const allGroups = allGroupsQuery.data || [];
  const memberIds = memberQuery.data || [];

  // While groups are still loading, render nothing to avoid a flash. Once
  // loaded, we still show the control even if there are zero groups — the
  // operator may want to create the first one (e.g. a new HOA/complex).
  if (allGroupsQuery.isLoading) {
    return null;
  }

  const nameById = new Map(allGroups.map((g) => [g.id, g.name]));
  const currentNames = memberIds.map((id) => nameById.get(id) || "").filter(Boolean);
  const working = draftIds ?? memberIds;

  function toggle(id: string) {
    setDraftIds((prev) => {
      const base = prev ?? memberIds;
      return base.includes(id) ? base.filter((x) => x !== id) : [...base, id];
    });
  }

  async function save() {
    setErrorMsg("");
    try {
      await setMutation.mutateAsync({ propertyId, groupIds: working });
      setEditing(false);
      setDraftIds(null);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not save groups");
    }
  }

  function cancel() {
    setEditing(false);
    setDraftIds(null);
    setErrorMsg("");
    setCreatingGroup(false);
    setNewGroupName("");
  }

  async function createAndSelect() {
    const name = newGroupName.trim();
    if (!name) return;
    setErrorMsg("");
    try {
      const created = await createMutation.mutateAsync({ name });
      const newId = String((created as { id?: string })?.id || "");
      if (newId) {
        // Auto-check the newly created group so the operator's next Save assigns it.
        setDraftIds((prev) => {
          const base = prev ?? memberIds;
          return base.includes(newId) ? base : [...base, newId];
        });
      }
      setCreatingGroup(false);
      setNewGroupName("");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not create group");
    }
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10.5px] uppercase tracking-[0.06em] text-tertiary">Groups</span>
        {!editing ? (
          <>
            {currentNames.length ? (
              currentNames.map((name) => (
                <Badge key={name} tone="default">{name}</Badge>
              ))
            ) : (
              <span className="text-xs text-tertiary">None</span>
            )}
            <button
              type="button"
              className="text-[11px] text-[var(--accent-600)] hover:underline bg-transparent border-0 cursor-pointer p-0"
              onClick={() => setEditing(true)}
            >
              Edit
            </button>
          </>
        ) : (
          <span className="text-xs text-tertiary">Select the groups this property belongs to</span>
        )}
      </div>

      {editing ? (
        <div className="flex flex-col gap-2 p-2.5 rounded-lg bg-raised border border-hairline">
          <div className="flex flex-wrap gap-x-4 gap-y-1.5">
            {allGroups.length ? (
              allGroups.map((group) => (
                <label key={group.id} className="flex items-center gap-1.5 text-xs text-secondary cursor-pointer">
                  <input
                    type="checkbox"
                    checked={working.includes(group.id)}
                    onChange={() => toggle(group.id)}
                    disabled={setMutation.isPending}
                  />
                  {group.name}
                </label>
              ))
            ) : (
              <span className="text-xs text-tertiary">No groups yet — create one below.</span>
            )}
          </div>

          {/* Inline create-a-group — collapsed until the operator needs it, so a
              missing group (new HOA/complex) can be made without leaving here. */}
          {creatingGroup ? (
            <div className="flex items-center gap-1.5">
              <Input
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                placeholder="New group name (e.g. Sandcastle Condos)"
                className="h-auto py-1 text-xs"
                disabled={createMutation.isPending}
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void createAndSelect();
                  }
                }}
              />
              <Button
                type="button"
                size="sm"
                disabled={createMutation.isPending || !newGroupName.trim()}
                onClick={() => void createAndSelect()}
              >
                {createMutation.isPending ? "Creating…" : "Create"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={createMutation.isPending}
                onClick={() => {
                  setCreatingGroup(false);
                  setNewGroupName("");
                }}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <button
              type="button"
              className="self-start text-[11px] text-[var(--accent-600)] hover:underline bg-transparent border-0 cursor-pointer p-0"
              onClick={() => setCreatingGroup(true)}
            >
              + New group
            </button>
          )}

          {errorMsg ? <p className="text-[11px] text-[var(--danger-text)] m-0">{errorMsg}</p> : null}
          <div className="flex gap-1.5">
            <Button type="button" size="sm" disabled={setMutation.isPending} onClick={() => void save()}>
              {setMutation.isPending ? "Saving…" : "Save"}
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={setMutation.isPending} onClick={cancel}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function PropertyExpansion({
  property,
  completeness,
  draftSignals,
  hasTraffic,
  kbEntries,
  kbLoading,
  kbError,
  assets,
  assetsLoading,
  assetsError,
  gaps,
  onUploadSuccess,
  onClose,
}: {
  property: PropertyRow;
  completeness: CompletenessResult;
  /** Portfolio-wide draft outcomes from dashboard-summary; per-property when
   *  that signal exists. Drives the training-arc stage. */
  draftSignals: DraftTrackRecord | null;
  /** Whether this property has enough guest traffic to judge readiness. */
  hasTraffic: boolean;
  kbEntries: PropertyKbEntry[] | null;
  kbLoading: boolean;
  kbError: string;
  assets: PropertyAsset[] | null;
  assetsLoading: boolean;
  assetsError: string;
  gaps: PropertyGap[];
  onUploadSuccess: (
    result: PropertyDocumentUploadResult,
    gap: PropertyGap | null,
  ) => Promise<{ resolved: boolean; requeued: number; pendingReview: boolean }>;
  onClose: () => void;
}) {
  const [uploadCollapsed, setUploadCollapsed] = useState(true);
  const [gapActionMessage, setGapActionMessage] = useState("");
  const [gapActionError, setGapActionError] = useState("");
  const [uploadGapId, setUploadGapId] = useState("");

  const completenessLabel = READINESS_LABELS[completeness.label];
  const scorePct = Math.round(completeness.score * 100);
  const completenessBreakdown = formatCompletenessBreakdown(completeness);

  // Training-arc stage for this property. Synthesizes the existing signals
  // (completeness, automation mode, traffic) with the draft track record.
  // draftSignals is portfolio-wide today; the model flags that honestly.
  const stageResult = resolveStage({
    completenessScore: completeness.score,
    hasTraffic,
    approvalMode: property.approvalMode,
    draftRecord: draftSignals ?? { approved: 0, edited: 0, rejected: 0 },
    draftRecordIsPortfolioWide: true,
  });

  const tags = [
    property.bedrooms != null ? `${property.bedrooms} bd` : "",
    property.bathrooms != null ? `${property.bathrooms} ba` : "",
    property.sleeps != null ? `sleeps ${property.sleeps}` : "",
  ].filter(Boolean);

  const amenities = [
    property.hasPool ? "Pool" : "",
    property.hasHotTub ? "Hot tub" : "",
    property.petsAllowed ? "Pet-friendly" : "",
  ].filter(Boolean);

  function openGapUpload(gapId: string) {
    setUploadGapId(gapId);
    setUploadCollapsed(false);
    setGapActionMessage("");
    setGapActionError("");
  }

  function clearGapUploadContext() {
    setUploadGapId("");
  }

  const sortedGaps = [...gaps].sort((left, right) => {
    if (right.askCount !== left.askCount) return right.askCount - left.askCount;
    const leftTime = left.lastAskedAt ? new Date(left.lastAskedAt).getTime() : 0;
    const rightTime = right.lastAskedAt ? new Date(right.lastAskedAt).getTime() : 0;
    return rightTime - leftTime;
  });

  const uploadGap = gaps.find((gap) => gap.id === uploadGapId) || null;
  const knowledgeEntriesHref = `/app/v2/knowledge?tab=entries&property=${encodeURIComponent(
    property.knowledgeRef,
  )}`;
  const knowledgeGapsHref = `/app/v2/knowledge?tab=gaps&property=${encodeURIComponent(
    property.knowledgeRef,
  )}`;
  const uploadPreset = useMemo<DocumentUploadPreset | null>(() => {
    if (!uploadGap) return null;
    return {
      contextKey: uploadGap.id,
      documentType: suggestedDocumentTypeForGap(uploadGap),
      target: "knowledge",
      scope: "property",
      sourceLabel: `dashboard_v2_gap_upload:${uploadGap.categorySlug || "general"}`,
      helperText: `Uploading to close gap: “${uploadGap.question}”`,
    };
  }, [uploadGap]);

  async function handleDocumentUploadSuccess(result: PropertyDocumentUploadResult) {
    try {
      const outcome = await onUploadSuccess(result, uploadGap);
      if (!uploadGap) return;
      setUploadGapId("");
      if (outcome.resolved) {
        setGapActionMessage(
          outcome.requeued > 0
            ? `Document uploaded. ${outcome.requeued} held ${
                outcome.requeued === 1 ? "inquiry" : "inquiries"
              } re-queued for the AI to retry.`
            : "Document uploaded and the gap was resolved.",
        );
        return;
      }
      if (outcome.pendingReview) {
        setGapActionMessage(
          "Document uploaded. Knowledge was staged for review, so this gap stays open until promotion completes.",
        );
        return;
      }
      setGapActionMessage(
        "Document uploaded. This gap will stay open until the uploaded knowledge becomes available to the AI.",
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Could not finish the gap follow-up.";
      setGapActionError(`Document uploaded, but the gap follow-up failed: ${message}`);
    }
  }

  useEffect(() => {
    if (!gapActionMessage && !gapActionError) return;
    const timeoutId = window.setTimeout(() => {
      setGapActionMessage("");
      setGapActionError("");
    }, 6000);
    return () => window.clearTimeout(timeoutId);
  }, [gapActionMessage, gapActionError]);

  return (
    <div className="px-[18px] pt-4 pb-5 border-t border-hairline bg-page flex flex-col gap-[18px]">
      <div className="flex justify-between gap-4 items-start">
        <div className="min-w-0 flex flex-col gap-1">
          <h3 className="text-[17px] font-semibold text-primary m-0">
            {property.propertyName || property.displayName || property.propertyCode}
          </h3>
          <p className="text-xs text-tertiary m-0">
            {[property.addressStreet, property.addressCity, property.addressState]
              .filter(Boolean)
              .join(", ") || property.propertyCode}
            {property.community ? ` · ${property.community}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <CompletenessChip
            label={completeness.label}
            scorePct={scorePct}
            displayLabel={completenessLabel.display}
            title={`${COMPLETENESS_TOOLTIP} ${completenessBreakdown}`}
          />
          <button
            type="button"
            className="appearance-none bg-transparent border-0 text-lg leading-none text-tertiary cursor-pointer px-2 py-1 rounded hover:bg-hover hover:text-primary"
            onClick={onClose}
            aria-label="Close property detail"
          >
            ×
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-2.5 p-3 px-3.5 rounded-[10px] bg-raised border border-hairline">
        {/* Training arc — where this property is in onboard -> monitor -> automate */}
        <div className="flex flex-col gap-1.5">
          <span className="text-[10.5px] uppercase tracking-[0.06em] text-tertiary">
            Training stage
          </span>
          <StageRail result={stageResult} />
        </div>
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <Badge key={tag} tone="default">
              {tag}
            </Badge>
          ))}
          {amenities.map((amenity) => (
            <Badge key={amenity} tone="info">
              {amenity}
            </Badge>
          ))}
          {property.community ? <Badge tone="accent">{property.community}</Badge> : null}
        </div>
        <div className="flex gap-2 items-baseline text-xs">
          <span className="text-[10.5px] uppercase tracking-[0.06em] text-tertiary">Autonomy</span>
          <span className="text-secondary">
            {describeAutonomy(property.approvalMode, property.minConfidenceForAuto)}
          </span>
        </div>
        <GroupMembershipEditor propertyId={property.id} />
        <div className="flex gap-2 text-[11.5px] text-tertiary flex-wrap">
          <span>{property.knowledgeCount} knowledge entries</span>
          <span>·</span>
          <span>{property.assetCount} asset records</span>
          <span>·</span>
          <span>Profile updated {formatDate(property.profileUpdatedAt)}</span>
        </div>
      </div>

      <div className="flex flex-col gap-2.5">
        <header className="flex justify-between items-center gap-2 w-full">
          <h4 className={SECTION_TITLE_CLS}>Gaps tagged to this property</h4>
          <div className="flex items-center gap-2">
            <span className={SECTION_COUNT_CLS}>{gaps.length}</span>
            <Button asChild variant="secondary" size="sm">
              <Link to={knowledgeGapsHref}>Open in Knowledge</Link>
            </Button>
          </div>
        </header>
        {gaps.length === 0 ? (
          <p className={SECTION_EMPTY_CLS}>No gaps tagged to this property.</p>
        ) : (
          <ul className="list-none m-0 p-0 flex flex-col gap-2">
            {sortedGaps.map((gap) => {
              const isFrequent = gap.askCount > 1;
              return (
                <li key={gap.id} className={ENTRY_BASE_CLS}>
                  <div className={cn(ENTRY_HEAD_CLS, "justify-between")}>
                    <div className="flex items-center gap-2.5 flex-wrap min-w-0">
                      <Badge tone={isFrequent ? "danger" : "warning"}>{gap.category}</Badge>
                      {isFrequent ? (
                        <Badge tone="danger">Asked {gap.askCount}×</Badge>
                      ) : null}
                      {gap.missingTopics.length ? (
                        <span className={ENTRY_META_CLS}>
                          Missing: {gap.missingTopics.join(", ")}
                        </span>
                      ) : null}
                      <span className={ENTRY_META_CLS}>
                        {formatRelativeAge(gap.lastAskedAt || gap.createdAt)}
                      </span>
                    </div>
                    <div className="flex gap-1.5 items-center flex-shrink-0">
                      <Button type="button" variant="secondary" size="sm" onClick={() => openGapUpload(gap.id)}>
                        Upload doc
                      </Button>
                      <Button asChild size="sm">
                        <Link to={knowledgeGapsHref}>Resolve in Knowledge</Link>
                      </Button>
                    </div>
                  </div>
                  <p className={ENTRY_Q_CLS}>{gap.question}</p>
                  <p className={ENTRY_META_CLS}>
                    Asked {gap.askCount} time{gap.askCount === 1 ? "" : "s"}
                    {gap.askCount > 1 && gap.lastAskedAt
                      ? ` · last asked ${formatRelativeAge(gap.lastAskedAt)}`
                      : ""}
                    {gap.reason ? ` · ${gap.reason.replace(/_/g, " ")}` : ""}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
        {gapActionMessage ? (
          <p className="mt-2.5 text-xs text-[var(--success-text)] m-0">{gapActionMessage}</p>
        ) : null}
        {gapActionError ? (
          <p className="mt-2.5 text-xs text-[var(--danger-text)] m-0">{gapActionError}</p>
        ) : null}
      </div>

      <div className="flex flex-col gap-2.5">
        <header className="flex justify-between items-center gap-2 w-full">
          <h4 className={SECTION_TITLE_CLS}>Knowledge</h4>
          <div className="flex items-center gap-2">
            <span className={SECTION_COUNT_CLS}>
              {kbEntries ? kbEntries.length : "…"}
            </span>
            <Button asChild variant="secondary" size="sm">
              <Link to={knowledgeEntriesHref}>Edit in Knowledge</Link>
            </Button>
          </div>
        </header>
        {kbLoading ? (
          <p className={SECTION_EMPTY_CLS}>Loading knowledge…</p>
        ) : kbError ? (
          <p className={SECTION_EMPTY_CLS}>{kbError}</p>
        ) : !kbEntries || kbEntries.length === 0 ? (
          <p className={SECTION_EMPTY_CLS}>
            No property knowledge captured yet. Upload a document here, or open Knowledge to add curated answers.
          </p>
        ) : (
          <div className="max-h-[420px] overflow-y-auto border border-hairline rounded-lg p-2 bg-raised">
            <ul className="list-none m-0 p-0 flex flex-col gap-2">
              {kbEntries.map((entry) => (
                <li key={entry.id} className={ENTRY_BASE_CLS}>
                  <div className={ENTRY_HEAD_CLS}>
                    <Badge tone="accent">{entry.category}</Badge>
                    <span className={ENTRY_META_CLS}>{Math.round(entry.confidence * 100)}%</span>
                    {entry.usageCount > 0 ? (
                      <span className={ENTRY_META_CLS}>{entry.usageCount} uses</span>
                    ) : null}
                    <span className={ENTRY_META_CLS}>{formatRelativeAge(entry.updatedAt)}</span>
                  </div>
                  <p className={ENTRY_Q_CLS}>{entry.question}</p>
                  <p className={ENTRY_BODY_CLS}>{entry.answer}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="flex flex-col gap-2.5">
        <header className="flex justify-between items-center gap-2 w-full">
          <h4 className={SECTION_TITLE_CLS}>Assets</h4>
          <span className={SECTION_COUNT_CLS}>{assets ? assets.length : "…"}</span>
        </header>
        {assetsLoading ? (
          <p className={SECTION_EMPTY_CLS}>Loading assets…</p>
        ) : assetsError ? (
          <p className={SECTION_EMPTY_CLS}>{assetsError}</p>
        ) : !assets || assets.length === 0 ? (
          <p className={SECTION_EMPTY_CLS}>
            No asset records yet. Upload warranties, manuals, or appliance docs to capture maintenance
            context.
          </p>
        ) : (
          <ul className="list-none m-0 p-0 flex flex-col gap-2">
            {assets.map((asset) => (
              <li key={asset.assetId} className={ENTRY_BASE_CLS}>
                <div className={ENTRY_HEAD_CLS}>
                  <strong className="text-sm text-primary">
                    {asset.assetName || asset.assetType || "Asset"}
                  </strong>
                  <Badge tone="default">{asset.assetType}</Badge>
                  <Badge tone={asset.status === "active" ? "success" : "warning"}>
                    {asset.status}
                  </Badge>
                </div>
                <p className={ENTRY_BODY_CLS}>
                  {asset.manufacturer || "Unknown manufacturer"}
                  {asset.modelNumber ? ` · ${asset.modelNumber}` : ""}
                  {asset.serialNumber ? ` · S/N ${asset.serialNumber}` : ""}
                </p>
                <p className={ENTRY_BODY_CLS}>
                  {asset.installDate ? `Installed ${formatDate(asset.installDate)}` : "Install date not recorded"}
                  {asset.lastServiceAt ? ` · Last serviced ${formatDate(asset.lastServiceAt)}` : ""}
                  {asset.warrantyEndDate ? ` · Warranty ends ${formatDate(asset.warrantyEndDate)}` : ""}
                </p>
                {asset.notes ? <p className={ENTRY_BODY_CLS}>{asset.notes}</p> : null}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex flex-col gap-2.5">
        <button
          type="button"
          className="appearance-none bg-transparent border-0 p-0 font-inherit cursor-pointer text-inherit flex justify-between items-center gap-2 w-full group"
          onClick={() => setUploadCollapsed((value) => !value)}
          aria-expanded={!uploadCollapsed}
        >
          <h4
            className={cn(SECTION_TITLE_CLS, "group-hover:text-[var(--accent-600)]")}
          >
            Upload document
          </h4>
          <span className="text-sm text-tertiary font-mono">
            {uploadCollapsed ? "+" : "−"}
          </span>
        </button>
        {!uploadCollapsed ? (
          <>
            {uploadGap ? (
              <div className="flex items-start justify-between gap-3 mb-2.5 px-3 py-2.5 rounded-lg bg-[color-mix(in_srgb,var(--surface-selected)_72%,transparent)] border border-[color-mix(in_srgb,var(--accent-500)_16%,var(--border-hairline))]">
                <div className="flex flex-col gap-0.5 min-w-0">
                  <strong className="text-[11px] uppercase tracking-[0.04em] text-primary">
                    Gap-anchored upload
                  </strong>
                  <span className="text-xs text-secondary">{uploadGap.question}</span>
                </div>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  onClick={clearGapUploadContext}
                >
                  Upload without gap
                </Button>
              </div>
            ) : null}
            <DocumentUploadForm
              property={property}
              preset={uploadPreset}
              onUploadSuccess={handleDocumentUploadSuccess}
            />
          </>
        ) : (
          <p className={SECTION_EMPTY_CLS}>
            Add house manuals, warranties, appliance docs, or guest Q&A files for this property.
          </p>
        )}
      </div>
    </div>
  );
}
