import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import {
  executeTodaySessionAction,
  requestTodaySessionFeedback,
  sendTodaySessionUpdate,
} from "./api";

export function useExecuteTodaySessionActionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, actionType }: { sessionId: string; actionType: string }) =>
      executeTodaySessionAction(sessionId, actionType),
    onSuccess: async (_result, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessions({ include_archived: false, limit: 200 }) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessionDetail(variables.sessionId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessionActions(variables.sessionId) }),
      ]);
    },
  });
}

export function useSendTodaySessionUpdateMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, messageText }: { sessionId: string; messageText: string }) =>
      sendTodaySessionUpdate(sessionId, { message_text: messageText }),
    onSuccess: async (_result, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessions({ include_archived: false, limit: 200 }) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessionDetail(variables.sessionId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessionActions(variables.sessionId) }),
      ]);
    },
  });
}

export function useRequestTodaySessionFeedbackMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId }: { sessionId: string }) => requestTodaySessionFeedback(sessionId),
    onSuccess: async (_result, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessions({ include_archived: false, limit: 200 }) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessionDetail(variables.sessionId) }),
        queryClient.invalidateQueries({ queryKey: queryKeys.today.sessionActions(variables.sessionId) }),
      ]);
    },
  });
}
