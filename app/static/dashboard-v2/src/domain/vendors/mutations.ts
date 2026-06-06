import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import {
  createVendor,
  createVendorCategory,
  deleteVendor,
  updateVendor,
} from "./api";

export function useCreateVendorCategoryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createVendorCategory,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.vendors.all() });
    },
  });
}

export function useCreateVendorMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createVendor,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.vendors.all() });
    },
  });
}

export function useUpdateVendorMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      vendorId,
      body,
    }: {
      vendorId: string;
      body: {
        name: string;
        category_slug: string;
        phone: string;
        website: string;
        ai_script: string;
        internal_notes: string;
        priority: number;
        apply_scope: string;
        property_ids: string[];
        active: boolean;
        operational_metadata?: Record<string, unknown>;
      };
    }) => updateVendor(vendorId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.vendors.all() });
    },
  });
}

export function useDeleteVendorMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteVendor,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.vendors.all() });
    },
  });
}
