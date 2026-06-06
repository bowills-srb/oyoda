import { useMutation, useQueryClient } from "@tanstack/react-query";

import { queryKeys } from "../../lib/query/queryKeys";

import { saveAutonomy } from "../autonomy/api";

import {
  createAlertContact,
  createPortfolio,
  deleteAlertContact,
  inviteTeamMember,
  markAlertContactAvailable,
  markAlertContactOOO,
  removeTeamMember,
  updateAlertContact,
  updatePortfolioProperties,
  updateSettings,
  updateTeamMemberRole,
  updateTeamMemberScopes,
} from "./api";

function invalidateSettingsQuery(queryClient: ReturnType<typeof useQueryClient>, key: "base" | "alert" | "team" | "portfolios") {
  if (key === "base") return queryClient.invalidateQueries({ queryKey: queryKeys.settings.base() });
  if (key === "alert") return queryClient.invalidateQueries({ queryKey: queryKeys.settings.alertRouting() });
  if (key === "team") return queryClient.invalidateQueries({ queryKey: queryKeys.settings.team() });
  return queryClient.invalidateQueries({ queryKey: queryKeys.settings.portfolios() });
}

export function useSaveSettingsAutonomyMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: saveAutonomy,
    onSuccess: async (payload) => {
      queryClient.setQueryData(queryKeys.autonomy.current(), payload);
      await queryClient.invalidateQueries({ queryKey: queryKeys.settings.base() });
    },
  });
}

export function useSaveSettingsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updateSettings,
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "base");
    },
  });
}

export function useCreateAlertContactMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createAlertContact,
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "alert");
    },
  });
}

export function useUpdateAlertContactMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ contactId, body }: { contactId: string; body: Record<string, unknown> }) =>
      updateAlertContact(contactId, body),
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "alert");
    },
  });
}

export function useMarkAlertContactOOOMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ contactId, body }: { contactId: string; body: Record<string, unknown> }) =>
      markAlertContactOOO(contactId, body),
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "alert");
    },
  });
}

export function useMarkAlertContactAvailableMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: markAlertContactAvailable,
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "alert");
    },
  });
}

export function useDeleteAlertContactMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAlertContact,
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "alert");
    },
  });
}

export function useInviteTeamMemberMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: inviteTeamMember,
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "team");
    },
  });
}

export function useUpdateTeamMemberRoleMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: string }) =>
      updateTeamMemberRole(memberId, role),
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "team");
    },
  });
}

export function useRemoveTeamMemberMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: removeTeamMember,
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "team");
    },
  });
}

export function useUpdateTeamMemberScopesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, scopes }: { memberId: string; scopes: unknown[] }) =>
      updateTeamMemberScopes(memberId, scopes),
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "team");
    },
  });
}

export function useCreatePortfolioMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createPortfolio,
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "portfolios");
    },
  });
}

export function useUpdatePortfolioPropertiesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ portfolioId, propertyExternalIds }: { portfolioId: string; propertyExternalIds: string[] }) =>
      updatePortfolioProperties(portfolioId, propertyExternalIds),
    onSuccess: async () => {
      await invalidateSettingsQuery(queryClient, "portfolios");
    },
  });
}
