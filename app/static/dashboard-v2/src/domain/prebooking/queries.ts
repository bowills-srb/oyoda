import { queryOptions } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";
import { fetchPreBookingMessageFeed } from "./api";

export function preBookingMessageFeedQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.prebooking.feed(),
    queryFn: fetchPreBookingMessageFeed,
    staleTime: 15_000,
  });
}
