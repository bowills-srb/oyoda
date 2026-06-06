import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import { resolveKbGap } from "./api";

export function useResolvePropertyGapMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ gapId, notes, retryTopic }: { gapId: string; notes: string; retryTopic: string }) =>
      resolveKbGap(gapId, { notes, retry_topic: retryTopic }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.properties.gaps(false) });
      await queryClient.invalidateQueries({ queryKey: queryKeys.properties.roster() });
    },
  });
}
