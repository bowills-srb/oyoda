import { queryOptions } from "@tanstack/react-query";

import { fetchAutonomy, fetchPortfolioAutonomy } from "./api";
import { queryKeys } from "../../lib/query/queryKeys";

export function autonomyQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.autonomy.current(),
    queryFn: fetchAutonomy,
    staleTime: 15_000,
  });
}

export function portfolioAutonomyQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.autonomy.portfolio(),
    queryFn: fetchPortfolioAutonomy,
    // Snapshots are written nightly; 5-minute stale keeps the hero fresh
    // without hammering the endpoint on every render.
    staleTime: 5 * 60 * 1_000,
  });
}
