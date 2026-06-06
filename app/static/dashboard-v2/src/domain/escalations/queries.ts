import { queryOptions } from "@tanstack/react-query";
import { queryKeys } from "../../lib/query/queryKeys";
import { fetchEscalations } from "./api";

export function escalationsQueryOptions(params?: { status?: string; limit?: number }) {
  return queryOptions({
    queryKey: queryKeys.escalations.list(params ?? {}),
    queryFn: () => fetchEscalations(params),
    staleTime: 15_000,
  });
}
