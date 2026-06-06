/**
 * Knowledge Proposals domain — the operator review queue for the brain
 * learning loop's durable-edit proposals.
 *
 * Backend: app/api/v1/endpoints/operator_knowledge_proposals.py
 *   GET    /app/api/knowledge-proposals
 *   POST   /app/api/knowledge-proposals/{id}/approve   { scope_type, scope_target_id?, proposed_answer?, proposed_question? }
 *   POST   /app/api/knowledge-proposals/{id}/reject    { review_notes? }
 *
 * A proposal is created when an operator makes a *durable* edit (a fact/policy/
 * price change, not a tone tweak) to a bound AI draft in the pre-booking queue.
 * Approving promotes the proposed knowledge into concierge_scoped_knowledge at
 * the operator-chosen scope; rejecting marks the edit as a one-off.
 *
 * Conventions mirror domain/knowledge (requestJson + queryOptions + useMutation).
 */

import { useMutation, useQueryClient, queryOptions } from "@tanstack/react-query";

import { requestJson } from "../../api/client";
import { queryKeys } from "../../lib/query/queryKeys";

// ── Types ────────────────────────────────────────────────────────────────────

// Scope choices map to the backend ExtractionStagingService scope types.
//   property        → applies to one property (scope_target_id = property UUID)
//   property_group  → applies to a group     (scope_target_id = group UUID)
//   tenant          → company-wide           (scope_target_id resolved server-side)
export type ProposalScope = "property" | "property_group" | "tenant";

export type KnowledgeProposal = {
  candidateId: string;
  scopeType: string;
  scopeTargetId: string;
  confidence: number;
  reviewStatus: string;
  proposedQuestion: string;
  proposedAnswer: string;
  proposedTopicId: string | null;
  editType: string;
  originalDraft: string;
  draftId: string;
  createdAt: string | null;
};

type RawProposal = {
  candidate_id?: string;
  scope_type?: string;
  scope_target_id?: string;
  confidence?: number;
  review_status?: string;
  proposed_question?: string;
  proposed_answer?: string;
  proposed_topic_id?: string | null;
  edit_type?: string;
  original_draft?: string;
  draft_id?: string;
  created_at?: string | null;
};

type RawProposalList = {
  count?: number;
  items?: RawProposal[];
  error?: string;
};

function normalizeProposal(raw: RawProposal): KnowledgeProposal {
  return {
    candidateId: String(raw.candidate_id || ""),
    scopeType: String(raw.scope_type || "property"),
    scopeTargetId: String(raw.scope_target_id || ""),
    confidence: Number(raw.confidence || 0),
    reviewStatus: String(raw.review_status || "pending"),
    proposedQuestion: String(raw.proposed_question || ""),
    proposedAnswer: String(raw.proposed_answer || ""),
    proposedTopicId: raw.proposed_topic_id ?? null,
    editType: String(raw.edit_type || ""),
    originalDraft: String(raw.original_draft || ""),
    draftId: String(raw.draft_id || ""),
    createdAt: raw.created_at ?? null,
  };
}

// ── API ──────────────────────────────────────────────────────────────────────

async function fetchKnowledgeProposals(): Promise<KnowledgeProposal[]> {
  const raw = await requestJson<RawProposalList>("/app/api/knowledge-proposals");
  const items = Array.isArray(raw?.items) ? raw.items : [];
  return items.map(normalizeProposal);
}

export type ApproveProposalBody = {
  scope_type: ProposalScope;
  scope_target_id?: string;
  proposed_question?: string;
  proposed_answer?: string;
  review_notes?: string;
};

function approveProposal(candidateId: string, body: ApproveProposalBody) {
  return requestJson<Record<string, unknown>>(
    `/app/api/knowledge-proposals/${encodeURIComponent(candidateId)}/approve`,
    { method: "POST", body },
  );
}

function rejectProposal(candidateId: string, reviewNotes?: string) {
  return requestJson<Record<string, unknown>>(
    `/app/api/knowledge-proposals/${encodeURIComponent(candidateId)}/reject`,
    { method: "POST", body: reviewNotes ? { review_notes: reviewNotes } : {} },
  );
}

// ── Query ────────────────────────────────────────────────────────────────────

export function knowledgeProposalsQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.knowledge.proposals(),
    queryFn: fetchKnowledgeProposals,
    staleTime: 30_000,
  });
}

// ── Property groups (real UUID-keyed groups for property_group scope) ─────────

export type PropertyGroupOption = {
  id: string;   // property_groups.id UUID — the scope_target_id for group scope
  name: string;
  groupType: string;
};

type RawPropertyGroup = { id?: string; name?: string; group_type?: string };
type RawPropertyGroupList = { count?: number; items?: RawPropertyGroup[] };

async function fetchPropertyGroups(): Promise<PropertyGroupOption[]> {
  const raw = await requestJson<RawPropertyGroupList>("/app/api/property-groups");
  const items = Array.isArray(raw?.items) ? raw.items : [];
  return items.map((g) => ({
    id: String(g.id || ""),
    name: String(g.name || ""),
    groupType: String(g.group_type || ""),
  }));
}

export function propertyGroupsQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.properties.groups(),
    queryFn: fetchPropertyGroups,
    staleTime: 30_000,
  });
}

// Create a new property group. Idempotent on name (server returns the existing
// group if one with the same name already exists for the tenant).
export type CreatePropertyGroupResult = {
  ok: boolean;
  alreadyExisted: boolean;
  id: string;
  name: string;
  groupType: string;
};

function createPropertyGroup(name: string, groupType?: string) {
  return requestJson<{
    ok?: boolean;
    already_existed?: boolean;
    id?: string;
    name?: string;
    group_type?: string;
  }>("/app/api/property-groups", {
    method: "POST",
    body: groupType ? { name, group_type: groupType } : { name },
  });
}

export function useCreatePropertyGroupMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name, groupType }: { name: string; groupType?: string }) =>
      createPropertyGroup(name, groupType),
    onSuccess: async () => {
      // New group should appear in group pickers and reconcile suggestions.
      await queryClient.invalidateQueries({ queryKey: queryKeys.properties.groups() });
      await queryClient.invalidateQueries({
        queryKey: [...queryKeys.properties.all(), "group-reconcile"],
      });
    },
  });
}

// ── A property's current group memberships (read + replace) ───────────────────
// Reads/writes property_group_memberships — the load-bearing grouping table the
// scoped-knowledge retrieval layer actually uses. Editing here is how a
// mis-tagged property gets corrected.

async function fetchPropertyMemberGroupIds(propertyId: string): Promise<string[]> {
  const raw = await requestJson<{ member_group_ids?: string[] }>(
    `/app/api/properties/${encodeURIComponent(propertyId)}/groups`,
  );
  return Array.isArray(raw?.member_group_ids) ? raw.member_group_ids.map(String) : [];
}

export function propertyMemberGroupsQueryOptions(propertyId: string) {
  return queryOptions({
    queryKey: [...queryKeys.properties.all(), "member-groups", propertyId] as const,
    queryFn: () => fetchPropertyMemberGroupIds(propertyId),
    staleTime: 30_000,
    enabled: Boolean(propertyId),
  });
}

function setPropertyMemberGroups(propertyId: string, groupIds: string[]) {
  return requestJson<Record<string, unknown>>(
    `/app/api/properties/${encodeURIComponent(propertyId)}/groups`,
    { method: "PUT", body: { group_ids: groupIds } },
  );
}

export function useSetPropertyMemberGroupsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ propertyId, groupIds }: { propertyId: string; groupIds: string[] }) =>
      setPropertyMemberGroups(propertyId, groupIds),
    onSuccess: async (_data, variables) => {
      await queryClient.invalidateQueries({
        queryKey: [...queryKeys.properties.all(), "member-groups", variables.propertyId],
      });
    },
  });
}

// ── Community ↔ membership reconcile (read-only drift diagnostic) ──────────────
// Reports properties whose `community` label and group memberships disagree, so
// an operator can fix each via the membership editor. Never writes.

export type ReconcileClassification =
  | "missing_membership"
  | "mismatched_membership"
  | "community_no_group";

export type ReconcileItem = {
  propertyId: string;
  propertyName: string;
  community: string;
  classification: ReconcileClassification;
  currentGroupIds: string[];
  currentGroupNames: string[];
  suggestedGroupId: string | null;
  suggestedGroupName: string;
};

type RawReconcileItem = {
  property_id?: string;
  property_name?: string;
  community?: string;
  classification?: string;
  current_group_ids?: string[];
  current_group_names?: string[];
  suggested_group_id?: string | null;
  suggested_group_name?: string;
};

async function fetchReconcile(): Promise<ReconcileItem[]> {
  const raw = await requestJson<{ items?: RawReconcileItem[] }>(
    "/app/api/property-group-reconcile",
  );
  const items = Array.isArray(raw?.items) ? raw.items : [];
  return items.map((it) => ({
    propertyId: String(it.property_id || ""),
    propertyName: String(it.property_name || ""),
    community: String(it.community || ""),
    classification: (String(it.classification || "") as ReconcileClassification),
    currentGroupIds: Array.isArray(it.current_group_ids) ? it.current_group_ids.map(String) : [],
    currentGroupNames: Array.isArray(it.current_group_names)
      ? it.current_group_names.map(String)
      : [],
    suggestedGroupId: it.suggested_group_id ?? null,
    suggestedGroupName: String(it.suggested_group_name || ""),
  }));
}

export function propertyGroupReconcileQueryOptions() {
  return queryOptions({
    queryKey: [...queryKeys.properties.all(), "group-reconcile"] as const,
    queryFn: fetchReconcile,
    staleTime: 30_000,
  });
}

// ── Mutations ────────────────────────────────────────────────────────────────

export function useApproveProposalMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ candidateId, body }: { candidateId: string; body: ApproveProposalBody }) =>
      approveProposal(candidateId, body),
    onSuccess: async () => {
      // A promotion writes scoped knowledge, so refresh the whole knowledge tree
      // (entries + proposals) so both reflect the new state.
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.all() });
    },
  });
}

export function useRejectProposalMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ candidateId, reviewNotes }: { candidateId: string; reviewNotes?: string }) =>
      rejectProposal(candidateId, reviewNotes),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.proposals() });
    },
  });
}
