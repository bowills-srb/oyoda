import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import { saveAutonomy } from "../autonomy/api";

import { approveInquiry, bindInquiryProperty, editInquiry, rejectInquiry } from "./api";

export function useApproveInquiryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: approveInquiry,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.prebooking.feed() });
    },
  });
}

export function useRejectInquiryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: rejectInquiry,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.prebooking.feed() });
    },
  });
}

export function useEditInquiryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, replyText }: { id: string; replyText: string }) =>
      editInquiry(id, { reply_text: replyText }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.prebooking.feed() });
    },
  });
}

export function useBindInquiryPropertyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: import("./types").BindPropertyInput }) =>
      bindInquiryProperty(id, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.prebooking.feed() });
    },
  });
}

export function useSaveAutonomyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: saveAutonomy,
    onSuccess: async (payload) => {
      queryClient.setQueryData(queryKeys.autonomy.current(), payload);
      await queryClient.invalidateQueries({ queryKey: queryKeys.prebooking.feed() });
    },
  });
}
