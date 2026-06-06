import { queryOptions } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import { fetchVendorCategories, fetchVendors } from "./api";
import { normalizeVendorCategories, normalizeVendors } from "./normalize";

export function vendorCategoriesQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.vendors.categories(),
    queryFn: async () => normalizeVendorCategories(await fetchVendorCategories()),
    staleTime: 30_000,
  });
}

export function vendorsListQueryOptions(params: { category: string; workflow: string }) {
  return queryOptions({
    queryKey: queryKeys.vendors.list(params),
    queryFn: async () =>
      normalizeVendors(
        await fetchVendors({
          category_slug: params.category || undefined,
          workflow: params.workflow || undefined,
        }),
      ),
    staleTime: 30_000,
  });
}
