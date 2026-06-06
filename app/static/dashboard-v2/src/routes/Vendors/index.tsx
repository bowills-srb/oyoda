import { useMemo, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { SurfaceErrorState } from "../../components/system/SurfaceErrorState";
import { SurfaceHeader } from "../../components/system/SurfaceHeader";
import { ListDetailSurface } from "../../components/system/ListDetailSurface";
import {
  vendorCategoriesQueryOptions,
  vendorsListQueryOptions,
} from "../../domain/vendors/queries";
import { useUrlState } from "../../shared/url-state/useUrlState";
import { CapabilityMap } from "./CapabilityMap";
import { CategoryDetailPanel } from "./CategoryDetailPanel";
import { deriveCoverage } from "./vendors_coverage";

/**
 * VendorsRoute — response-coverage surface (redesigned).
 *
 * Replaces the old stacked-forms-then-table layout with a capability map:
 * categories grouped into dispatch (maintenance) and experience (recreational)
 * lanes, each showing coverage at a glance, with a detail panel for the
 * selected category. The full CRUD lives inside the panel, reached by
 * selecting a category — not as the landing.
 *
 * Set-once surface: an operator configures coverage and rarely returns, so the
 * landing reads like a calm service-area configuration, and an empty system
 * (zero vendors) reads as healthy opportunity rather than broken.
 *
 * Portability: this composes self-contained pieces (CapabilityMap +
 * CategoryDetailPanel) so the same surface can later be embedded under Settings
 * or Escalations without rework — only this thin orchestrator is route-bound.
 */

const DEFAULTS = { selected: "" };

export default function VendorsRoute() {
  const [urlState, setUrlState] = useUrlState(DEFAULTS);
  const [mutationError, setMutationError] = useState<Error | null>(null);

  // Both queries pull the full set; coverage + per-category vendors are derived
  // client-side. No workflow/category server filter — the capability map shows
  // every category at once, which is the point.
  const categoriesQuery = useQuery(vendorCategoriesQueryOptions());
  const vendorsQuery = useQuery(vendorsListQueryOptions({ category: "", workflow: "" }));

  const categories = categoriesQuery.data || [];
  const vendors = vendorsQuery.data || [];

  const loading = categoriesQuery.isLoading || vendorsQuery.isLoading;
  const loadError =
    (categoriesQuery.error as Error | null) || (vendorsQuery.error as Error | null) || null;

  const coverage = useMemo(() => deriveCoverage(categories, vendors), [categories, vendors]);

  const selectedSlug = urlState.selected || null;
  const selectedCoverage = useMemo(
    () => coverage.find((c) => c.category.slug === selectedSlug) || null,
    [coverage, selectedSlug],
  );

  function selectCategory(slug: string) {
    setMutationError(null);
    setUrlState({ selected: slug });
  }

  function closeDetail() {
    setUrlState({ selected: "" });
  }

  async function handleRetry() {
    setMutationError(null);
    await Promise.all([categoriesQuery.refetch(), vendorsQuery.refetch()]);
  }

  return (
    <main className="grid grid-rows-[auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-hidden">
      <SurfaceHeader
        title="Response coverage"
        subtitle="Set up who your AI can route guests and issues to. Configure once — anything not set up routes to you."
      />

      {loadError ? (
        <SurfaceErrorState
          title="Coverage failed to load"
          detail={loadError.message}
          onRetry={handleRetry}
        />
      ) : (
        <div className="min-h-0">
          {mutationError ? (
            <p className="m-0 border-b border-hairline bg-[var(--danger-fill)] px-5 py-2 text-[12.5px] text-[var(--danger-text)]">
              {mutationError.message}
            </p>
          ) : null}
          <ListDetailSurface
            detailOpen={Boolean(selectedCoverage)}
            onCloseDetail={closeDetail}
            detailAriaLabel="Category coverage detail"
            list={
              <CapabilityMap
                coverage={coverage}
                selectedSlug={selectedSlug}
                onSelect={selectCategory}
                loading={loading}
              />
            }
            detail={
              selectedCoverage ? (
                <CategoryDetailPanel
                  coverage={selectedCoverage}
                  vendors={vendors}
                  onError={setMutationError}
                />
              ) : null
            }
          />
        </div>
      )}
    </main>
  );
}
