import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useListKeyboardNav } from "../../shared/hooks/useListKeyboardNav";
import { renderInlineError } from "../../adapters/index.js";
import { Badge } from "../../components/primitives/Badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { SurfaceHeader } from "../../components/system/SurfaceHeader";
import { SurfaceControls } from "../../components/system/SurfaceControls";
import { cn } from "../../lib/utils";
import { useResolvePropertyGapMutation } from "../../domain/properties/mutations";
import {
  propertyGroupReconcileQueryOptions,
  useSetPropertyMemberGroupsMutation,
  type ReconcileItem,
} from "../../domain/knowledgeProposals";
import {
  propertiesGapsQueryOptions,
  propertiesPortfoliosQueryOptions,
  propertiesRosterQueryOptions,
  propertyAssetsQueryOptions,
  propertyKbQueryOptions,
} from "../../domain/properties/queries";
import { dashboardSummaryQueryOptions } from "../../domain/dashboard/queries";
import type { DraftTrackRecord } from "../../domain/trainingArc/stageModel";
import { queryKeys } from "../../lib/query/queryKeys";
import { useUrlState } from "../../shared/url-state/useUrlState";

import { PropertyExpansion } from "./PropertyExpansion";
import {
  COMPLETENESS_TOOLTIP,
  calculateCompleteness,
  deriveCompletenessInputs,
  formatCompletenessBreakdown,
} from "./completeness";
import { READINESS_LABELS } from "./readiness";
import {
  buildPropertyGapIndex,
  gapsForProperty,
  propertiesWithGaps,
  unboundGapCount,
} from "./gapGrouping";
import type {
  CompletenessResult,
  PortfolioOption,
  PropertyDocumentUploadResult,
  PropertyGap,
  PropertyRow,
} from "./types";

/**
 * PropertiesRoute — v2 Properties surface.
 *
 * See docs/PROPERTIES_V2_CONTRACT.md for the full backend contract and
 * docs/scratch/PROPERTIES_V2_DESIGN.md for design rationale.
 */

type ViewMode = "row" | "grid";
type StatusFilter = "" | "well-documented" | "has-gaps" | "bare-bones";

const URL_DEFAULTS = {
  view: "row" as ViewMode,
  q: "",
  portfolio: "",
  community: "",
  status: "" as StatusFilter,
  selected: "",
};

function communityOptionLabel(community: string): string {
  const normalized = community.trim();
  if (!normalized) return "";
  if (normalized.toLowerCase() === "other") return "Uncategorized";
  return normalized
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function describeEmptySliceCopy(
  portfolios: PortfolioOption[],
  {
    portfolio,
    community,
    status,
    search,
  }: {
    portfolio: string;
    community: string;
    status: StatusFilter;
    search: string;
  },
): string {
  const filters: string[] = [];
  if (portfolio) {
    const portfolioMatch = portfolios.find((item) => item.portfolioKey === portfolio);
    filters.push(portfolioMatch?.displayName || portfolio);
  }
  if (community) {
    filters.push(communityOptionLabel(community));
  }
  if (status) {
    filters.push(READINESS_LABELS[status].display);
  }
  if (search.trim()) {
    filters.push(`"${search.trim()}"`);
  }
  if (filters.length === 0) {
    return "Try a different portfolio, community, status filter, or search query.";
  }
  return `No properties match ${filters.join(" · ")}. Try a different portfolio, community, status filter, or search query.`;
}

// ── Completeness chip ────────────────────────────────────────────────────────
// Inline Tailwind chip replacing legacy `property-row-completeness*` family.
// Tone keyed by completeness label — preserves the three legacy variants.

type CompletenessChipProps = {
  label: "well-documented" | "has-gaps" | "bare-bones";
  scorePct: number;
  displayLabel: string;
  title: string;
};

function CompletenessChip({ label, scorePct, displayLabel, title }: CompletenessChipProps) {
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

// ── MetricChip ───────────────────────────────────────────────────────────────
// Inline Tailwind chip replacing legacy `properties-metric-chip*` family.

type MetricChipTone = "default" | "strong" | "warn" | "danger" | "info";

function MetricChip({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: MetricChipTone;
}) {
  return (
    <div
      className={cn(
        "grid gap-1 px-3.5 py-3 rounded-[10px] border bg-raised",
        tone === "default" && "border-hairline",
        tone === "strong" && "border-border bg-sunken",
        tone === "warn" && "border-[color-mix(in_srgb,var(--warning-spine)_25%,transparent)]",
        tone === "danger" && "border-[color-mix(in_srgb,var(--danger-spine)_25%,transparent)]",
        tone === "info" && "border-[color-mix(in_srgb,var(--accent-500)_25%,transparent)]",
      )}
    >
      <span className="text-[11px] uppercase tracking-[0.06em] text-tertiary">{label}</span>
      <span className="text-[22px] font-semibold text-primary tabular-nums">{value}</span>
    </div>
  );
}

// --- Component --------------------------------------------------------------

// ── Group reconcile banner ────────────────────────────────────────────────────
// Quiet, diagnostic-only drift report: appears only when community labels and
// group memberships disagree. Each item routes to the property (opening the
// membership editor). The one inline action is the purely-additive safe case
// (missing_membership with a clear suggested group) — never a destructive
// auto-replace. Mismatches and unmatched communities go to manual review.

const RECONCILE_LABELS: Record<ReconcileItem["classification"], string> = {
  missing_membership: "Not in its community group",
  mismatched_membership: "In a different group than its community",
  community_no_group: "Community has no matching group",
};

function GroupReconcileBanner({
  items,
  onReview,
}: {
  items: ReconcileItem[];
  onReview: (propertyId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const setGroupsMutation = useSetPropertyMemberGroupsMutation();
  const bannerQueryClient = useQueryClient();
  const [busyId, setBusyId] = useState("");

  if (items.length === 0) return null;

  async function addToSuggested(item: ReconcileItem) {
    if (!item.suggestedGroupId) return;
    setBusyId(item.propertyId);
    try {
      // Purely additive: keep any existing memberships, add the suggested group.
      const next = Array.from(new Set([...item.currentGroupIds, item.suggestedGroupId]));
      await setGroupsMutation.mutateAsync({ propertyId: item.propertyId, groupIds: next });
      // Refresh the drift report so the now-fixed item drops out of the banner.
      await bannerQueryClient.invalidateQueries({
        queryKey: [...queryKeys.properties.all(), "group-reconcile"],
      });
    } finally {
      setBusyId("");
    }
  }

  return (
    <section className="mb-4 rounded-lg border border-[color-mix(in_srgb,var(--warning-spine)_28%,var(--border-hairline))] bg-[var(--warning-fill)] overflow-hidden">
      <button
        type="button"
        className="w-full flex items-center justify-between gap-3 px-3.5 py-2.5 bg-transparent border-0 cursor-pointer text-left"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="flex items-center gap-2 min-w-0">
          <strong className="text-[13px] font-semibold text-[var(--warning-text)]">
            {items.length} propert{items.length === 1 ? "y" : "ies"} with group mismatches
          </strong>
          <span className="text-[12px] text-secondary truncate">
            community label and group membership disagree
          </span>
        </span>
        <span className="text-[11px] text-secondary flex-shrink-0">{open ? "Hide" : "Review"}</span>
      </button>

      {open ? (
        <div className="flex flex-col divide-y divide-[var(--border-hairline)] border-t border-[var(--border-hairline)]">
          {items.map((item) => (
            <div key={item.propertyId} className="flex items-center gap-3 px-3.5 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <strong className="text-[12.5px] text-primary truncate">{item.propertyName}</strong>
                  <span className="text-[11px] text-tertiary">{communityOptionLabel(item.community)}</span>
                </div>
                <span className="text-[11.5px] text-secondary">
                  {RECONCILE_LABELS[item.classification]}
                  {item.currentGroupNames.length
                    ? ` · currently: ${item.currentGroupNames.filter(Boolean).join(", ")}`
                    : ""}
                </span>
              </div>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                {item.classification === "missing_membership" && item.suggestedGroupId ? (
                  <Button
                    type="button"
                    size="sm"
                    disabled={busyId === item.propertyId}
                    onClick={() => void addToSuggested(item)}
                  >
                    {busyId === item.propertyId ? "Adding…" : `Add to ${item.suggestedGroupName}`}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() => onReview(item.propertyId)}
                >
                  Review
                </Button>
              </div>
            </div>
          ))}
          {items.some((it) => it.classification === "community_no_group") ? (
            <p className="text-[11px] text-tertiary m-0 px-3.5 py-2 leading-snug">
              “Community has no matching group” means no group exists for that community name yet —
              open the property via Review to create the group and assign it, or assign it to an existing group.
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export default function PropertiesRoute() {
  const queryClient = useQueryClient();
  const resolveGapMutation = useResolvePropertyGapMutation();
  const [urlState, updateUrl] = useUrlState(URL_DEFAULTS);
  const propertiesQuery = useQuery(propertiesRosterQueryOptions());
  const portfoliosQuery = useQuery(propertiesPortfoliosQueryOptions());
  const gapsQuery = useQuery(propertiesGapsQueryOptions(false));
  const reconcileQuery = useQuery(propertyGroupReconcileQueryOptions());
  const dashboardSummaryQuery = useQuery(dashboardSummaryQueryOptions());

  // Portfolio-wide draft track record from dashboard-summary. Per-property
  // draft signals don't exist yet, so every property's training stage reads
  // the same record; the stage model flags this as portfolio-wide in its copy.
  const portfolioDraftRecord: DraftTrackRecord | null =
    dashboardSummaryQuery.data?.pre_booking.draft_signals ?? null;
  const properties = propertiesQuery.data ?? null;
  const gaps = gapsQuery.data ?? [];
  const portfolios = portfoliosQuery.data ?? [];
  const loading = propertiesQuery.isLoading || portfoliosQuery.isLoading || gapsQuery.isLoading;
  const queryError =
    propertiesQuery.error instanceof Error
      ? propertiesQuery.error
      : portfoliosQuery.error instanceof Error
        ? portfoliosQuery.error
        : gapsQuery.error instanceof Error
          ? gapsQuery.error
          : null;
  const loadError = queryError ? queryError.message : "";
  const authFailed = Boolean(loadError) && /401|403|unauthorized|forbidden/i.test(loadError);

  const gapIndex = useMemo(() => buildPropertyGapIndex(gaps), [gaps]);
  const totalWithGaps = useMemo(() => propertiesWithGaps(gapIndex), [gapIndex]);
  const totalUnboundGaps = useMemo(() => unboundGapCount(gaps), [gaps]);
  const communities = useMemo(() => {
    if (!properties) return [];
    return Array.from(
      new Set(
        properties
          .map((property) => property.community.trim())
          .filter(Boolean),
      ),
    ).sort((left, right) => communityOptionLabel(left).localeCompare(communityOptionLabel(right)));
  }, [properties]);

  const propertyCompleteness = useMemo<Record<string, CompletenessResult>>(() => {
    const result: Record<string, CompletenessResult> = {};
    if (!properties) return result;
    for (const property of properties) {
      const tagged = gapsForProperty(gapIndex, property.knowledgeRef);
      const inputs = deriveCompletenessInputs(property, tagged.length > 0);
      result[property.knowledgeRef] = calculateCompleteness(inputs);
    }
    return result;
  }, [properties, gapIndex]);

  const visibleProperties = useMemo<PropertyRow[]>(() => {
    if (!properties) return [];
    const search = urlState.q.trim().toLowerCase();
    let portfolioCodes: Set<string> | null = null;
    if (urlState.portfolio) {
      const portfolio = portfolios.find((p) => p.portfolioKey === urlState.portfolio);
      portfolioCodes = new Set((portfolio?.propertyExternalIds || []).map((s: string) => s.trim()).filter(Boolean));
    }
    return properties.filter((property) => {
      if (portfolioCodes && !portfolioCodes.has(property.propertyCode)) return false;
      if (urlState.community && property.community !== urlState.community) return false;
      if (urlState.status) {
        const completeness = propertyCompleteness[property.knowledgeRef];
        if (!completeness || completeness.label !== urlState.status) return false;
      }
      if (!search) return true;
      const haystack = [
        property.propertyCode,
        property.propertyName,
        property.displayName,
        property.marketingName,
        property.addressStreet,
        property.addressCity,
        property.community,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(search);
    });
  }, [
    properties,
    portfolios,
    propertyCompleteness,
    urlState.community,
    urlState.q,
    urlState.portfolio,
    urlState.status,
  ]);

  const portfolioTotals = useMemo(() => {
    const totals = { total: 0, wellDocumented: 0, hasGaps: 0, bareBones: 0 };
    if (!properties) return totals;
    totals.total = properties.length;
    for (const property of properties) {
      const completeness = propertyCompleteness[property.knowledgeRef];
      if (!completeness) continue;
      if (completeness.label === "well-documented") totals.wellDocumented += 1;
      else if (completeness.label === "has-gaps") totals.hasGaps += 1;
      else if (completeness.label === "bare-bones") totals.bareBones += 1;
    }
    return totals;
  }, [properties, propertyCompleteness]);

  // Keyboard navigation: row view only (grid modal has its own focus trap).
  const visiblePropertyIds = useMemo(
    () => (urlState.view === "row" ? visibleProperties.map((p) => p.knowledgeRef) : []),
    [visibleProperties, urlState.view],
  );
  useListKeyboardNav({
    itemIds: visiblePropertyIds,
    selectedId: urlState.selected,
    onSelect: (id) => updateUrl({ selected: id }, { replace: true }),
    onClose: closeSelection,
    // Disable keyboard nav while grid modal is open to avoid moving the background list
    enabled: urlState.view === "row",
  });

  const emptySliceCopy = useMemo(
    () =>
      describeEmptySliceCopy(portfolios, {
        portfolio: urlState.portfolio,
        community: urlState.community,
        status: urlState.status,
        search: urlState.q,
      }),
    [portfolios, urlState.community, urlState.portfolio, urlState.q, urlState.status],
  );

  const selectedProperty = useMemo(
    () => properties?.find((p) => p.knowledgeRef === urlState.selected) ?? null,
    [properties, urlState.selected],
  );
  const selectedKbQuery = useQuery({
    ...propertyKbQueryOptions(selectedProperty?.knowledgeRef || ""),
    enabled: Boolean(selectedProperty?.knowledgeRef),
  });
  const selectedAssetsQuery = useQuery({
    ...propertyAssetsQueryOptions(selectedProperty?.propertyCode || ""),
    enabled: Boolean(selectedProperty?.propertyCode),
  });

  const handleUploadSuccess = useCallback(
    async (
      ref: string,
      result: PropertyDocumentUploadResult,
      gap: PropertyGap | null,
    ): Promise<{ resolved: boolean; requeued: number; pendingReview: boolean }> => {
      const autoPromotedKnowledge = Number(result.knowledge_result?.auto_promoted_count ?? 0);
      const stagedKnowledge = Number(result.knowledge_result?.staged_for_review_count ?? 0);
      const importedGuestQa = Number(result.guest_qa_result?.imported_answers ?? 0);
      const canResolveGap = autoPromotedKnowledge > 0 || importedGuestQa > 0;

      let resolved = false;
      let requeued = 0;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.properties.kb(ref) }),
        selectedProperty?.propertyCode
          ? queryClient.invalidateQueries({ queryKey: queryKeys.properties.assets(selectedProperty.propertyCode) })
          : Promise.resolve(),
      ]);
      if (gap && canResolveGap) {
        const resolveResult = await resolveGapMutation.mutateAsync({
          gapId: gap.id,
          notes: `Resolved via document upload: ${result.filename || "uploaded document"}`,
          retryTopic: gap.categorySlug,
        });
        resolved = true;
        requeued = Number(
          (resolveResult as { triggered_regeneration_count?: number })?.triggered_regeneration_count ?? 0,
        );
      }
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.properties.roster() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.properties.gaps(false) }),
      ]);
      return {
        resolved,
        requeued,
        pendingReview: Boolean(gap && !canResolveGap && stagedKnowledge > 0),
      };
    },
    [queryClient, resolveGapMutation, selectedProperty?.propertyCode],
  );

  function openProperty(property: PropertyRow) {
    if (urlState.selected === property.knowledgeRef) return;
    updateUrl({ selected: property.knowledgeRef }, { replace: true });
  }

  function closeSelection() {
    updateUrl({ selected: "" }, { replace: true });
  }

  useEffect(() => {
    if (!urlState.selected) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") closeSelection();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlState.selected]);

  const viewToggleBtn = (mode: ViewMode, label: string) => (
    <button
      type="button"
      role="tab"
      aria-selected={urlState.view === mode}
      className={cn(
        "appearance-none border-0 px-3 py-1 text-xs font-medium rounded-md cursor-pointer transition-colors duration-100",
        urlState.view === mode
          ? "bg-raised text-primary shadow-[0_1px_2px_rgba(15,23,42,0.06)]"
          : "bg-transparent text-secondary hover:text-primary",
      )}
      onClick={() => updateUrl({ view: mode }, { replace: true })}
    >
      {label}
    </button>
  );

  return (
    <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
      <SurfaceHeader
        title="Property Readiness"
        subtitle="Can Oyvoda safely operate each property? Coverage, gaps, and the context the AI needs to handle guests without you."
        summaryLine={
          properties
            ? `${portfolioTotals.wellDocumented} high readiness · ${portfolioTotals.hasGaps} need coverage · ${portfolioTotals.bareBones} blocked`
            : undefined
        }
      />

      <SurfaceControls ariaLabel="Properties controls">
        <div className="flex items-center gap-2 px-7 py-3 border-b border-hairline max-[860px]:flex-col max-[860px]:items-stretch">
          <div
            className="inline-flex bg-hover border border-hairline rounded-lg p-0.5 gap-0.5"
            role="tablist"
            aria-label="View mode"
          >
            {viewToggleBtn("row", "Row")}
            {viewToggleBtn("grid", "Grid")}
          </div>
          <label className="min-w-0 flex-1 flex items-center gap-2 px-2.5 bg-hover border border-transparent rounded-md focus-within:bg-raised focus-within:border-border">
            <Input
              type="search"
              className="h-auto py-1.5 text-[12.5px] border-0 bg-transparent shadow-none focus-visible:ring-0 focus-visible:ring-offset-0 px-0"
              placeholder="Search properties…"
              value={urlState.q}
              onChange={(event) => updateUrl({ q: event.target.value }, { replace: true })}
            />
          </label>
          <Select
            className="h-auto py-1.5 text-[12.5px] font-medium rounded-md text-secondary w-auto"
            value={urlState.portfolio}
            onChange={(event) => updateUrl({ portfolio: event.target.value }, { replace: true })}
            aria-label="Portfolio filter"
          >
            <option value="">All portfolios</option>
            {portfolios.map((portfolio) => (
              <option key={portfolio.portfolioKey} value={portfolio.portfolioKey}>
                {portfolio.displayName} ({portfolio.propertyCount})
              </option>
            ))}
          </Select>
          <Select
            className="h-auto py-1.5 text-[12.5px] font-medium rounded-md text-secondary w-auto"
            value={urlState.community}
            onChange={(event) => updateUrl({ community: event.target.value }, { replace: true })}
            aria-label="Community filter"
          >
            <option value="">All communities</option>
            {communities.map((community) => (
              <option key={community} value={community}>
                {communityOptionLabel(community)}
              </option>
            ))}
          </Select>
          <Select
            className="h-auto py-1.5 text-[12.5px] font-medium rounded-md text-secondary w-auto"
            value={urlState.status}
            onChange={(event) =>
              updateUrl({ status: event.target.value as StatusFilter }, { replace: true })
            }
            aria-label="Status filter"
          >
            <option value="">All status</option>
            <option value="well-documented">{READINESS_LABELS["well-documented"].filterOptionLabel}</option>
            <option value="has-gaps">{READINESS_LABELS["has-gaps"].filterOptionLabel}</option>
            <option value="bare-bones">{READINESS_LABELS["bare-bones"].filterOptionLabel}</option>
          </Select>
        </div>
      </SurfaceControls>

      <div className="px-7 py-4">
        {authFailed ? (
          <section className="flex items-center justify-between gap-4 mb-3 px-3.5 py-3 rounded-lg border bg-[var(--warning-fill)] border-[color-mix(in_srgb,var(--warning-spine)_28%,var(--border-hairline))]">
            <div className="flex flex-col gap-0.5 min-w-0">
              <strong className="text-[13px] font-semibold text-[var(--warning-text)]">
                Session expired.
              </strong>
              <span className="text-[12.5px] text-secondary leading-[1.45]">
                Properties data could not be loaded.
              </span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <Button asChild variant="secondary" size="sm">
                <a href="/app">Sign in</a>
              </Button>
            </div>
          </section>
        ) : null}

        {loadError ? (
          <section className="flex items-center justify-between gap-4 mb-3 px-3.5 py-3 rounded-lg border bg-[var(--danger-fill)] border-[color-mix(in_srgb,var(--danger-spine)_28%,var(--border-hairline))]">
            <div className="flex flex-col gap-0.5 min-w-0">
              <strong className="text-[13px] font-semibold text-[var(--danger-text)]">
                Could not load properties.
              </strong>
              <span className="text-[12.5px] text-secondary leading-[1.45]">{loadError}</span>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  void propertiesQuery.refetch();
                  void portfoliosQuery.refetch();
                  void gapsQuery.refetch();
                }}
              >
                Retry
              </Button>
            </div>
          </section>
        ) : null}

        {reconcileQuery.data && reconcileQuery.data.length > 0 ? (
          <GroupReconcileBanner
            items={reconcileQuery.data}
            onReview={(propertyId) => {
              // Banner carries the property UUID; the row selection key is
              // knowledgeRef. Map UUID -> knowledgeRef to open the right row.
              const match = properties?.find((p) => p.id === propertyId);
              if (match) updateUrl({ selected: match.knowledgeRef }, { replace: true });
            }}
          />
        ) : null}

        <section className="grid grid-cols-[repeat(auto-fit,minmax(160px,1fr))] gap-2.5 mb-4">
          <MetricChip label="Total properties" value={portfolioTotals.total} tone="strong" />
          <MetricChip label={READINESS_LABELS["well-documented"].display} value={portfolioTotals.wellDocumented} />
          <MetricChip label={READINESS_LABELS["has-gaps"].display} value={portfolioTotals.hasGaps} tone="warn" />
          <MetricChip label={READINESS_LABELS["bare-bones"].display} value={portfolioTotals.bareBones} tone="danger" />
          <MetricChip
            label="Properties with tagged gaps"
            value={totalWithGaps}
            tone="info"
          />
          {totalUnboundGaps > 0 ? (
            <p className="col-span-full text-[11.5px] text-tertiary m-0 pt-1.5 px-1">
              {totalUnboundGaps} open gap{totalUnboundGaps === 1 ? "" : "s"} are not tagged to a specific
              property. Per-property gap counts are a floor, not an exhaustive list.
            </p>
          ) : null}
        </section>

        {loading ? (
          <section className="queue-empty">{renderInlineError(
            "Loading properties…",
            "Pulling autonomy, identity coverage, and gap context.",
          )}</section>
        ) : !properties || properties.length === 0 ? (
          <section className="queue-empty">
            <h3 className="empty-title">No properties linked yet.</h3>
            <p className="empty-copy">
              Contact support to wire your PMS, or upload a property table to get started.
            </p>
          </section>
        ) : visibleProperties.length === 0 ? (
          <section className="queue-empty">
            <h3 className="empty-title">No properties match this slice.</h3>
            <p className="empty-copy">{emptySliceCopy}</p>
          </section>
        ) : urlState.view === "row" ? (
          <section className="flex flex-col gap-1.5">
            {visibleProperties.map((property) => {
              const isSelected = urlState.selected === property.knowledgeRef;
              const completeness = propertyCompleteness[property.knowledgeRef] || {
                score: 0,
                label: "bare-bones" as const,
              };
              const completenessLabel = READINESS_LABELS[completeness.label];
              const completenessTitle = `${COMPLETENESS_TOOLTIP} ${formatCompletenessBreakdown(completeness)}`;
              const tagged = gapsForProperty(gapIndex, property.knowledgeRef);
              const tags = [
                property.bedrooms != null ? `${property.bedrooms}bd` : "",
                property.bathrooms != null ? `${property.bathrooms}ba` : "",
                property.sleeps != null ? `sleeps ${property.sleeps}` : "",
              ].filter(Boolean);
              return (
                <article
                  key={property.id || property.propertyCode}
                  data-keyboard-nav-id={property.knowledgeRef}
                  className={cn(
                    "border rounded-[10px] bg-raised overflow-hidden transition-[border-color,box-shadow] duration-[120ms]",
                    isSelected
                      ? "border-[var(--accent-600)] shadow-[0_0_0_1px_var(--accent-glow)]"
                      : "border-hairline hover:border-border",
                  )}
                >
                  <button
                    type="button"
                    className={cn(
                      "appearance-none w-full border-0 bg-transparent text-left font-inherit cursor-pointer",
                      "grid grid-cols-[minmax(280px,1.6fr)_minmax(160px,180px)_minmax(200px,220px)_auto] items-center gap-4 px-4 py-3.5",
                      "disabled:cursor-default",
                      !isSelected && "hover:bg-hover",
                    )}
                    onClick={() => openProperty(property)}
                    aria-expanded={isSelected}
                    disabled={isSelected}
                  >
                    <div className="min-w-0 flex flex-col gap-0.5">
                      <strong className="text-sm text-primary whitespace-nowrap overflow-hidden text-ellipsis">
                        {property.propertyName || property.displayName || property.propertyCode}
                      </strong>
                      <span className="text-[11.5px] text-tertiary">
                        {[property.addressStreet, property.community].filter(Boolean).join(" · ")}
                      </span>
                    </div>
                    <div className="flex gap-1.5 flex-wrap min-w-0">
                      {tags.map((tag) => (
                        <span
                          key={tag}
                          className="text-[11px] text-secondary px-1.5 py-0.5 bg-hover rounded"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                    <div className="flex items-center justify-end gap-2 text-xs text-secondary whitespace-nowrap min-w-0 text-right tabular-nums">
                      <span className="flex-none">{property.knowledgeCount} KB</span>
                      <span className="text-tertiary">·</span>
                      <span className="flex-none">{property.assetCount} assets</span>
                      {tagged.length > 0 ? (
                        <Badge tone="warning">
                          {tagged.length} gap{tagged.length === 1 ? "" : "s"}
                        </Badge>
                      ) : null}
                    </div>
                    <CompletenessChip
                      label={completeness.label}
                      scorePct={Math.round(completeness.score * 100)}
                      displayLabel={completenessLabel.display}
                      title={completenessTitle}
                    />
                  </button>
                  {isSelected ? (
                    <PropertyExpansion
                      property={property}
                      completeness={completeness}
                      draftSignals={portfolioDraftRecord}
                      hasTraffic={tagged.length > 0 || property.knowledgeCount > 0}
                      kbEntries={selectedProperty?.knowledgeRef === property.knowledgeRef ? (selectedKbQuery.data ?? null) : null}
                      kbLoading={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedKbQuery.isLoading}
                      kbError={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedKbQuery.error instanceof Error ? selectedKbQuery.error.message : ""}
                      assets={selectedProperty?.knowledgeRef === property.knowledgeRef ? (selectedAssetsQuery.data ?? null) : null}
                      assetsLoading={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedAssetsQuery.isLoading}
                      assetsError={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedAssetsQuery.error instanceof Error ? selectedAssetsQuery.error.message : ""}
                      gaps={tagged}
                      onUploadSuccess={(result, gap) => handleUploadSuccess(property.knowledgeRef, result, gap)}
                      onClose={closeSelection}
                    />
                  ) : null}
                </article>
              );
            })}
          </section>
        ) : (
          <section className="grid grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-3">
            {visibleProperties.map((property) => {
              const completeness = propertyCompleteness[property.knowledgeRef] || {
                score: 0,
                label: "bare-bones" as const,
              };
              const completenessLabel = READINESS_LABELS[completeness.label];
              const completenessTitle = `${COMPLETENESS_TOOLTIP} ${formatCompletenessBreakdown(completeness)}`;
              const tagged = gapsForProperty(gapIndex, property.knowledgeRef);
              const initials = (
                property.propertyName ||
                property.displayName ||
                property.propertyCode ||
                "??"
              )
                .split(/\s+/)
                .map((part) => part.charAt(0).toUpperCase())
                .slice(0, 2)
                .join("");
              const hashSource = property.propertyCode || property.knowledgeRef;
              let hash = 0;
              for (let i = 0; i < hashSource.length; i += 1) {
                hash = (hash * 31 + hashSource.charCodeAt(i)) | 0;
              }
              const hue = ((hash % 360) + 360) % 360;
              return (
                <button
                  key={property.id || property.propertyCode}
                  type="button"
                  className="appearance-none border border-hairline bg-raised rounded-xl p-3.5 flex flex-col gap-2 items-start text-left cursor-pointer font-inherit transition-[border-color,transform] duration-[120ms] hover:border-border hover:-translate-y-px dark:[&_.property-card-thumb]:brightness-[1.15]"
                  onClick={() => openProperty(property)}
                >
                  <span
                    className="property-card-thumb w-11 h-11 rounded-[10px] flex items-center justify-center text-sm font-semibold tracking-[0.04em]"
                    aria-hidden="true"
                    style={{ backgroundColor: `hsl(${hue} 35% 28%)`, color: `hsl(${hue} 60% 80%)` }}
                  >
                    {initials}
                  </span>
                  <strong className="text-[13.5px] text-primary leading-[1.3]">
                    {property.propertyName || property.displayName || property.propertyCode}
                  </strong>
                  {property.community ? (
                    <span className="text-[11px] text-[var(--accent-700)]">{property.community}</span>
                  ) : null}
                  <div className="flex items-center gap-1.5 text-[11.5px] text-secondary flex-wrap">
                    <span>{property.knowledgeCount} KB</span>
                    <span>·</span>
                    <span>{property.assetCount} assets</span>
                    {tagged.length > 0 ? <Badge tone="warning">{tagged.length} gaps</Badge> : null}
                  </div>
                  <CompletenessChip
                    label={completeness.label}
                    scorePct={Math.round(completeness.score * 100)}
                    displayLabel={completenessLabel.display}
                    title={completenessTitle}
                  />
                </button>
              );
            })}
          </section>
        )}
      </div>

      {/* Grid view opens detail in a modal. Same component, different chrome. */}
      {urlState.view === "grid" && urlState.selected
        ? (() => {
            const property = visibleProperties.find((p) => p.knowledgeRef === urlState.selected);
            if (!property) return null;
            const completeness = propertyCompleteness[property.knowledgeRef] || {
              score: 0,
              label: "bare-bones" as const,
            };
            const tagged = gapsForProperty(gapIndex, property.knowledgeRef);
            return (
              <div
                className="fixed inset-0 z-[80] flex items-center justify-center px-4 py-8 bg-[rgba(15,23,42,0.45)] dark:bg-[rgba(0,0,0,0.55)]"
                role="dialog"
                aria-modal="true"
                aria-label="Property detail"
                onClick={(event) => {
                  if (event.target === event.currentTarget) closeSelection();
                }}
              >
                <div className="bg-page rounded-[14px] max-w-[880px] w-full max-h-full overflow-y-auto shadow-[0_20px_60px_rgba(15,23,42,0.35)]">
                  <PropertyExpansion
                    property={property}
                    completeness={completeness}
                    draftSignals={portfolioDraftRecord}
                    hasTraffic={tagged.length > 0 || property.knowledgeCount > 0}
                    kbEntries={selectedProperty?.knowledgeRef === property.knowledgeRef ? (selectedKbQuery.data ?? null) : null}
                    kbLoading={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedKbQuery.isLoading}
                    kbError={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedKbQuery.error instanceof Error ? selectedKbQuery.error.message : ""}
                    assets={selectedProperty?.knowledgeRef === property.knowledgeRef ? (selectedAssetsQuery.data ?? null) : null}
                    assetsLoading={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedAssetsQuery.isLoading}
                    assetsError={selectedProperty?.knowledgeRef === property.knowledgeRef && selectedAssetsQuery.error instanceof Error ? selectedAssetsQuery.error.message : ""}
                    gaps={tagged}
                    onUploadSuccess={(result, gap) => handleUploadSuccess(property.knowledgeRef, result, gap)}
                    onClose={closeSelection}
                  />
                </div>
              </div>
            );
          })()
        : null}
    </main>
  );
}
