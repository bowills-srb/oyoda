import { queryOptions } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";
import { fetchDashboardSummary } from "./api";

export function dashboardSummaryQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.dashboard.summary(),
    queryFn: fetchDashboardSummary,
    staleTime: 30_000,
  });
}
