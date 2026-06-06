import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import {
  createKnowledgeEntry,
  deleteKnowledgeEntry,
  dismissKnowledgeGap,
  resolveKnowledgeGap,
  saveKnowledgeGuidance,
  testKnowledgeQuestion,
  updateKnowledgeEntry,
} from "./api";
import { normalizeKnowledgeGuidance, normalizeKnowledgeTestResult } from "./normalize";

export function useCreateKnowledgeEntryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createKnowledgeEntry,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.all() });
    },
  });
}

export function useUpdateKnowledgeEntryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, body }: { entryId: string; body: { question: string; answer: string; category: string } }) =>
      updateKnowledgeEntry(entryId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.all() });
    },
  });
}

export function useDeleteKnowledgeEntryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteKnowledgeEntry,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.all() });
    },
  });
}

export function useResolveKnowledgeGapMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      gapId,
      body,
    }: {
      gapId: string;
      body: { add_to_kb: boolean; answer: string; notes: string; retry_topic: string };
    }) => resolveKnowledgeGap(gapId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.all() });
    },
  });
}

export function useDismissKnowledgeGapMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: dismissKnowledgeGap,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.all() });
    },
  });
}

export function useSaveKnowledgeGuidanceMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: saveKnowledgeGuidance,
    onSuccess: async (payload) => {
      queryClient.setQueryData(queryKeys.knowledge.guidance(), normalizeKnowledgeGuidance(payload));
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.guidance() });
    },
  });
}

export function useTestKnowledgeQuestionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (question: string) => normalizeKnowledgeTestResult(await testKnowledgeQuestion(question)),
    onSuccess: async (payload) => {
      if (!payload.answered) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.gaps(false) });
      }
    },
  });
}
