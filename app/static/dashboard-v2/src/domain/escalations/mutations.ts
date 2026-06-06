import { useMutation, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "../../lib/query/queryKeys";
import { assignEscalation, dispatchVendor, resolveEscalation, saveCoordination } from "./api";

function useEscalationMutation<TInput>(
  fn: (ticketId: string, body: TInput) => Promise<{ ok: boolean }>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ ticketId, body }: { ticketId: string; body: TInput }) =>
      fn(ticketId, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.escalations.all() });
    },
  });
}

export function useAssignEscalation() {
  return useEscalationMutation(assignEscalation);
}

export function useResolveEscalation() {
  return useEscalationMutation(resolveEscalation);
}

export function useDispatchVendor() {
  return useEscalationMutation(dispatchVendor);
}

export function useSaveCoordination() {
  return useEscalationMutation(saveCoordination);
}
