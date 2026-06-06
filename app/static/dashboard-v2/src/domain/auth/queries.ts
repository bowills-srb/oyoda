import { queryOptions } from "@tanstack/react-query";

import { fetchSession } from "./api";
import { queryKeys } from "../../lib/query/queryKeys";

export function sessionQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.auth.session(),
    queryFn: fetchSession,
    staleTime: 60_000,
  });
}
