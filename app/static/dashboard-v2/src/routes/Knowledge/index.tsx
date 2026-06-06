import { useEffect, useMemo, useState } from "react";

import { useQuery, useQueryClient } from "@tanstack/react-query";

import { SurfaceErrorState } from "../../components/system/SurfaceErrorState";
import { SurfaceHeader } from "../../components/system/SurfaceHeader";
import { SurfaceControls } from "../../components/system/SurfaceControls";
import { SurfaceTabs } from "../../components/system/SurfaceTabs";
import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import {
  useCreateKnowledgeEntryMutation,
  useDeleteKnowledgeEntryMutation,
  useDismissKnowledgeGapMutation,
  useResolveKnowledgeGapMutation,
  useSaveKnowledgeGuidanceMutation,
  useTestKnowledgeQuestionMutation,
  useUpdateKnowledgeEntryMutation,
} from "../../domain/knowledge/mutations";
import {
  knowledgeEntriesQueryOptions,
  knowledgeGapsQueryOptions,
  knowledgeGuidanceQueryOptions,
} from "../../domain/knowledge/queries";
import type {
  KnowledgeEntry,
  KnowledgeGap,
  KnowledgeTestResult,
} from "../../domain/knowledge/types";
import { propertiesRosterQueryOptions } from "../../domain/properties/queries";
import {
  knowledgeProposalsQueryOptions,
  propertyGroupsQueryOptions,
  useApproveProposalMutation,
  useRejectProposalMutation,
  type KnowledgeProposal,
  type ProposalScope,
} from "../../domain/knowledgeProposals";
import { queryKeys } from "../../lib/query/queryKeys";
import { useUrlState } from "../../shared/url-state/useUrlState";

const DEFAULTS = {
  tab: "entries",
  property: "",
  q: "",
  resolved: false,
};

type KnowledgeTab = "entries" | "gaps" | "guidance" | "proposals";

type PropertyOption = {
  label: string;
  value: string;
};

const ENTRY_CREATE_DEFAULT = {
  question: "",
  answer: "",
  category: "General",
  propertyRef: "",
};

function formatDateTime(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatPercent(value: number): string {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

export default function KnowledgeRoute() {
  const [urlState, setUrlState] = useUrlState(DEFAULTS);
  const activeTab = (urlState.tab || "entries") as KnowledgeTab;
  const queryClient = useQueryClient();

  const [error, setError] = useState<Error | null>(null);
  const [entryDraft, setEntryDraft] = useState({
    ...ENTRY_CREATE_DEFAULT,
    propertyRef: urlState.property || "",
  });
  const [editingEntryId, setEditingEntryId] = useState("");
  const [editDraft, setEditDraft] = useState({ question: "", answer: "", category: "" });
  const [deletingEntryId, setDeletingEntryId] = useState("");
  const [gapDrafts, setGapDrafts] = useState<Record<string, { answer: string; notes: string; addToKb: boolean }>>({});
  const [gapBusyId, setGapBusyId] = useState("");
  const [guidanceDraft, setGuidanceDraft] = useState("");
  const [testQuestion, setTestQuestion] = useState("");
  const [testResult, setTestResult] = useState<KnowledgeTestResult | null>(null);
  // Per-proposal review drafts: chosen scope, optional scope target (property/
  // group id), and an editable answer the operator can refine before promoting.
  const [proposalDrafts, setProposalDrafts] = useState<
    Record<string, { scope: ProposalScope; scopeTargetId: string; answer: string }>
  >({});
  const [proposalBusyId, setProposalBusyId] = useState("");

  const rosterQuery = useQuery(propertiesRosterQueryOptions());
  const entriesQuery = useQuery({
    ...knowledgeEntriesQueryOptions(urlState.property || ""),
    enabled: activeTab === "entries",
  });
  const gapsQuery = useQuery({
    ...knowledgeGapsQueryOptions(Boolean(urlState.resolved)),
    enabled: activeTab === "gaps",
  });
  const guidanceQuery = useQuery({
    ...knowledgeGuidanceQueryOptions(),
    enabled: activeTab === "guidance",
  });
  const proposalsQuery = useQuery({
    ...knowledgeProposalsQueryOptions(),
    enabled: activeTab === "proposals",
  });
  const propertyGroupsQuery = useQuery({
    ...propertyGroupsQueryOptions(),
    enabled: activeTab === "proposals",
  });

  const createEntryMutation = useCreateKnowledgeEntryMutation();
  const updateEntryMutation = useUpdateKnowledgeEntryMutation();
  const deleteEntryMutation = useDeleteKnowledgeEntryMutation();
  const resolveGapMutation = useResolveKnowledgeGapMutation();
  const dismissGapMutation = useDismissKnowledgeGapMutation();
  const saveGuidanceMutation = useSaveKnowledgeGuidanceMutation();
  const testQuestionMutation = useTestKnowledgeQuestionMutation();
  const approveProposalMutation = useApproveProposalMutation();
  const rejectProposalMutation = useRejectProposalMutation();

  useEffect(() => {
    if (guidanceQuery.data) {
      setGuidanceDraft(guidanceQuery.data.guidanceText);
    }
  }, [guidanceQuery.data]);

  const propertyOptions = useMemo<PropertyOption[]>(
    () =>
      (rosterQuery.data || [])
        .map((property) => ({
          label:
            property.propertyName ||
            property.displayName ||
            property.marketingName ||
            property.propertyCode ||
            property.externalId,
          value: property.knowledgeRef,
        }))
        .filter((option) => option.value)
        .sort((a, b) => a.label.localeCompare(b.label)),
    [rosterQuery.data],
  );

  const entries = entriesQuery.data || [];
  const gaps = gapsQuery.data || [];
  const proposals = proposalsQuery.data || [];
  const propertyGroups = propertyGroupsQuery.data || [];
  const guidance = guidanceQuery.data || {
    guidanceText: "",
    updatedBy: null,
    updatedAt: null,
    charLimit: 8000,
  };

  const filteredEntries = useMemo(() => {
    const query = urlState.q.trim().toLowerCase();
    return entries.filter((entry) => {
      if (!query) return true;
      return [entry.question, entry.answer, entry.category, entry.propertyLabel].some((field) =>
        String(field || "").toLowerCase().includes(query),
      );
    });
  }, [entries, urlState.q]);

  const filteredGaps = useMemo(() => {
    const query = urlState.q.trim().toLowerCase();
    const propertyFilter = urlState.property.trim().toLowerCase();
    return gaps.filter((gap) => {
      const matchingPropertyLabels = propertyOptions
        .filter((option) => option.value.toLowerCase() === propertyFilter)
        .map((option) => option.label.toLowerCase());
      if (
        propertyFilter &&
        ![String(gap.property || "").toLowerCase(), ...matchingPropertyLabels].includes(
          String(gap.property || "").toLowerCase(),
        )
      ) {
        return false;
      }
      if (!query) return true;
      return [gap.question, gap.category, gap.property, gap.reason, ...(gap.missingTopics || [])].some((field) =>
        String(field || "").toLowerCase().includes(query),
      );
    });
  }, [gaps, propertyOptions, urlState.property, urlState.q]);

  const counts = useMemo(
    () => ({
      entries: entries.length,
      gaps: gaps.length,
      guidance: guidanceDraft.trim() ? 1 : 0,
      proposals: proposals.length,
    }),
    [entries.length, gaps.length, guidanceDraft, proposals.length],
  );

  const loading =
    rosterQuery.isLoading ||
    (activeTab === "entries" ? entriesQuery.isLoading : false) ||
    (activeTab === "gaps" ? gapsQuery.isLoading : false) ||
    (activeTab === "guidance" ? guidanceQuery.isLoading : false) ||
    (activeTab === "proposals" ? proposalsQuery.isLoading : false);

  const currentError =
    error ||
    (rosterQuery.error as Error | null) ||
    (entriesQuery.error as Error | null) ||
    (gapsQuery.error as Error | null) ||
    (guidanceQuery.error as Error | null) ||
    (proposalsQuery.error as Error | null) ||
    null;

  function resetEntryDraft() {
    setEntryDraft({
      ...ENTRY_CREATE_DEFAULT,
      propertyRef: urlState.property || "",
    });
  }

  function gapDraftFor(gapId: string) {
    return gapDrafts[gapId] || { answer: "", notes: "", addToKb: true };
  }

  async function handleRefresh() {
    setError(null);
    await Promise.all([
      rosterQuery.refetch(),
      activeTab === "entries"
        ? entriesQuery.refetch()
        : activeTab === "gaps"
          ? gapsQuery.refetch()
          : guidanceQuery.refetch(),
    ]);
  }

  async function handleCreateEntry() {
    if (!entryDraft.question.trim() || !entryDraft.answer.trim()) return;
    setError(null);
    try {
      await createEntryMutation.mutateAsync({
        question: entryDraft.question.trim(),
        answer: entryDraft.answer.trim(),
        category: entryDraft.category.trim() || "General",
        property_external_id: entryDraft.propertyRef || "__all_properties__",
        retry_topic: "",
      });
      resetEntryDraft();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to create KB entry"));
    }
  }

  function beginEdit(entry: KnowledgeEntry) {
    setEditingEntryId(entry.id);
    setEditDraft({
      question: entry.question,
      answer: entry.answer,
      category: entry.category,
    });
  }

  async function handleSaveEntry(entryId: string) {
    if (!editDraft.question.trim() || !editDraft.answer.trim()) return;
    setError(null);
    try {
      await updateEntryMutation.mutateAsync({
        entryId,
        body: {
          question: editDraft.question.trim(),
          answer: editDraft.answer.trim(),
          category: editDraft.category.trim() || "General",
        },
      });
      setEditingEntryId("");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to update KB entry"));
    }
  }

  async function handleDeleteEntry(entryId: string) {
    setDeletingEntryId(entryId);
    setError(null);
    try {
      await deleteEntryMutation.mutateAsync(entryId);
      if (editingEntryId === entryId) setEditingEntryId("");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to delete KB entry"));
    } finally {
      setDeletingEntryId("");
    }
  }

  async function handleResolveGap(gap: KnowledgeGap) {
    const draft = gapDraftFor(gap.id);
    setGapBusyId(gap.id);
    setError(null);
    try {
      await resolveGapMutation.mutateAsync({
        gapId: gap.id,
        body: {
          add_to_kb: draft.addToKb,
          answer: draft.answer.trim(),
          notes: draft.notes.trim(),
          retry_topic: gap.categorySlug || "",
        },
      });
      setGapDrafts((current) => {
        const next = { ...current };
        delete next[gap.id];
        return next;
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to resolve KB gap"));
    } finally {
      setGapBusyId("");
    }
  }

  async function handleDismissGap(gapId: string) {
    setGapBusyId(gapId);
    setError(null);
    try {
      await dismissGapMutation.mutateAsync(gapId);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to dismiss KB gap"));
    } finally {
      setGapBusyId("");
    }
  }

  async function handleSaveGuidance() {
    setError(null);
    try {
      await saveGuidanceMutation.mutateAsync({ guidance_text: guidanceDraft });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to save AI guidance"));
    }
  }

  async function handleRunTest() {
    if (!testQuestion.trim()) return;
    setError(null);
    try {
      const payload = await testQuestionMutation.mutateAsync(testQuestion.trim());
      setTestResult(payload);
      if (!payload.answered) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.knowledge.gaps(false) });
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to test KB question"));
    }
  }

  function proposalDraftFor(proposal: KnowledgeProposal) {
    return (
      proposalDrafts[proposal.candidateId] || {
        // Default to the candidate's existing scope (property) and its target,
        // and the proposed answer as-is — the operator can change any of these.
        scope: (proposal.scopeType as ProposalScope) || "property",
        scopeTargetId: proposal.scopeTargetId || "",
        answer: proposal.proposedAnswer,
      }
    );
  }

  function setProposalDraft(
    candidateId: string,
    patch: Partial<{ scope: ProposalScope; scopeTargetId: string; answer: string }>,
    base: { scope: ProposalScope; scopeTargetId: string; answer: string },
  ) {
    setProposalDrafts((current) => ({
      ...current,
      [candidateId]: { ...base, ...patch },
    }));
  }

  async function handleApproveProposal(proposal: KnowledgeProposal) {
    const draft = proposalDraftFor(proposal);
    // Property / group scope need a concrete target; company-wide (tenant)
    // resolves server-side so no target is required.
    if (draft.scope !== "tenant" && !draft.scopeTargetId) {
      setError(new Error("Choose a property (or group) for this scope before approving."));
      return;
    }
    setProposalBusyId(proposal.candidateId);
    setError(null);
    try {
      await approveProposalMutation.mutateAsync({
        candidateId: proposal.candidateId,
        body: {
          scope_type: draft.scope,
          scope_target_id: draft.scope === "tenant" ? undefined : draft.scopeTargetId,
          proposed_answer: draft.answer.trim() || undefined,
        },
      });
      setProposalDrafts((current) => {
        const next = { ...current };
        delete next[proposal.candidateId];
        return next;
      });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to approve proposal"));
    } finally {
      setProposalBusyId("");
    }
  }

  async function handleRejectProposal(proposal: KnowledgeProposal) {
    setProposalBusyId(proposal.candidateId);
    setError(null);
    try {
      await rejectProposalMutation.mutateAsync({ candidateId: proposal.candidateId });
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to reject proposal"));
    } finally {
      setProposalBusyId("");
    }
  }

  const headerSubtitle =
    activeTab === "entries"
      ? "Scoped knowledge entries now flow through the canonical dashboard KB service."
      : activeTab === "gaps"
        ? "Review unresolved questions, promote answers into the KB, and retry held drafts."
        : activeTab === "proposals"
          ? "Review what the AI learned from your edits, then promote it into property, group, or company-wide knowledge."
          : "Set operator guidance that shapes the AI without inventing a second knowledge path.";

  return (
    <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
      <SurfaceHeader title="Knowledge" subtitle={headerSubtitle} />

      <SurfaceControls ariaLabel="Knowledge controls">
        <SurfaceTabs
          ariaLabel="Knowledge views"
          tabs={[
            { key: "entries", label: "Entries", count: counts.entries },
            { key: "gaps", label: "Gaps", count: counts.gaps },
            { key: "proposals", label: "Proposals", count: counts.proposals },
            { key: "guidance", label: "AI guidance", count: counts.guidance },
          ]}
          activeKey={activeTab}
          loading={loading}
          onSelect={(key) => setUrlState({ tab: key as KnowledgeTab }, { replace: true })}
        />
        <div className="filter-bar">
          <label className="filter-search">
            <Input
              value={urlState.q}
              onChange={(event) => setUrlState({ q: event.target.value }, { replace: true })}
              placeholder={activeTab === "guidance" ? "Search test results or guidance context" : "Search this view"}
              aria-label="Search knowledge"
            />
          </label>
          <Select
            value={urlState.property}
            onChange={(event) => setUrlState({ property: event.target.value }, { replace: true })}
            aria-label="Property filter"
            disabled={activeTab === "guidance"}
          >
            <option value="">All properties</option>
            {propertyOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
          {activeTab === "gaps" ? (
            <Button
              type="button"
              variant={urlState.resolved ? "secondary" : "default"}
              size="sm"
              onClick={() => setUrlState({ resolved: !urlState.resolved }, { replace: true })}
            >
              {urlState.resolved ? "Showing resolved" : "Showing unresolved"}
            </Button>
          ) : (
            <Button type="button" variant="secondary" size="sm" onClick={() => void handleRefresh()}>
              Refresh
            </Button>
          )}
        </div>
      </SurfaceControls>

      {currentError ? <SurfaceErrorState title="Knowledge load failed" detail={currentError.message} onRetry={handleRefresh} /> : null}

      {activeTab === "entries" ? (
        <section className="knowledge-shell">
          <section className="knowledge-panel knowledge-panel-form">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Create entry</p>
              <h2 className="panel-title">Add portfolio or property knowledge</h2>
            </div>
            <div className="knowledge-form-grid">
              <label className="knowledge-field">
                <span className="knowledge-label">Question</span>
                <Input
                  value={entryDraft.question}
                  onChange={(event) => setEntryDraft((current) => ({ ...current, question: event.target.value }))}
                  placeholder="What time is check-in?"
                />
              </label>
              <label className="knowledge-field">
                <span className="knowledge-label">Category</span>
                <Input
                  value={entryDraft.category}
                  onChange={(event) => setEntryDraft((current) => ({ ...current, category: event.target.value }))}
                  placeholder="General"
                />
              </label>
              <label className="knowledge-field">
                <span className="knowledge-label">Property scope</span>
                <Select
                  value={entryDraft.propertyRef}
                  onChange={(event) => setEntryDraft((current) => ({ ...current, propertyRef: event.target.value }))}
                >
                  <option value="">All properties</option>
                  {propertyOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </label>
              <label className="knowledge-field knowledge-field-wide">
                <span className="knowledge-label">Answer</span>
                <Textarea
                  rows={5}
                  value={entryDraft.answer}
                  onChange={(event) => setEntryDraft((current) => ({ ...current, answer: event.target.value }))}
                  placeholder="Check-in begins at 4:00 PM. We’ll send the access instructions on arrival day."
                />
              </label>
            </div>
            <div className="knowledge-actions">
              <Button
                type="button"
                size="sm"
                disabled={createEntryMutation.isPending}
                onClick={() => void handleCreateEntry()}
              >
                {createEntryMutation.isPending ? "Saving…" : "Save entry"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={createEntryMutation.isPending}
                onClick={resetEntryDraft}
              >
                Reset
              </Button>
            </div>
          </section>

          <section className="knowledge-panel knowledge-panel-test">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Test retrieval</p>
              <h2 className="panel-title">Ask the knowledge base a real question</h2>
            </div>
            <div className="knowledge-test-row">
              <Input
                value={testQuestion}
                onChange={(event) => setTestQuestion(event.target.value)}
                placeholder="Is there beach gear at this property?"
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={testQuestionMutation.isPending}
                onClick={() => void handleRunTest()}
              >
                {testQuestionMutation.isPending ? "Testing…" : "Run test"}
              </Button>
            </div>
            {testResult ? (
              <div className={`knowledge-test-result ${testResult.answered ? "is-answered" : "is-gap"}`}>
                <strong>
                  {testResult.answered
                    ? `Matched at ${formatPercent(testResult.confidence)}`
                    : `No confident match (${formatPercent(testResult.confidence)})`}
                </strong>
                <p>{testResult.answer}</p>
                {testResult.matchQuestion ? <span>Matched: {testResult.matchQuestion}</span> : null}
              </div>
            ) : null}
          </section>

          <section className="knowledge-panel knowledge-panel-list">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Entries</p>
              <h2 className="panel-title">{loading ? "Loading entries…" : `${filteredEntries.length} entries in view`}</h2>
            </div>
            {loading ? (
              <div className="queue-empty">
                <h3 className="empty-title">Loading knowledge entries…</h3>
              </div>
            ) : filteredEntries.length === 0 ? (
              <div className="queue-empty">
                <h3 className="empty-title">No entries match this slice.</h3>
                <p className="empty-copy">Try another property filter or add the missing answer above.</p>
              </div>
            ) : (
              <div className="knowledge-list">
                {filteredEntries.map((entry) => {
                  const isEditing = editingEntryId === entry.id;
                  return (
                    <article key={entry.id} className="knowledge-card">
                      <div className="knowledge-card-head">
                        <div>
                          <h3 className="knowledge-card-title">{entry.question}</h3>
                          <p className="knowledge-card-meta">
                            <span>{entry.category}</span>
                            <span>·</span>
                            <span>{entry.propertyLabel}</span>
                            <span>·</span>
                            <span>{entry.usageCount} uses</span>
                            <span>·</span>
                            <span>{formatPercent(entry.confidence)}</span>
                          </p>
                        </div>
                        <div className="knowledge-actions">
                          {isEditing ? (
                            <>
                              <Button
                                type="button"
                                size="sm"
                                disabled={updateEntryMutation.isPending}
                                onClick={() => void handleSaveEntry(entry.id)}
                              >
                                Save
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={updateEntryMutation.isPending}
                                onClick={() => setEditingEntryId("")}
                              >
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <Button type="button" variant="secondary" size="sm" onClick={() => beginEdit(entry)}>
                              Edit
                            </Button>
                          )}
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={deletingEntryId === entry.id}
                            onClick={() => void handleDeleteEntry(entry.id)}
                          >
                            {deletingEntryId === entry.id ? "Deleting…" : "Delete"}
                          </Button>
                        </div>
                      </div>
                      {isEditing ? (
                        <div className="knowledge-form-grid">
                          <label className="knowledge-field">
                            <span className="knowledge-label">Question</span>
                            <Input
                              value={editDraft.question}
                              onChange={(event) => setEditDraft((current) => ({ ...current, question: event.target.value }))}
                            />
                          </label>
                          <label className="knowledge-field">
                            <span className="knowledge-label">Category</span>
                            <Input
                              value={editDraft.category}
                              onChange={(event) => setEditDraft((current) => ({ ...current, category: event.target.value }))}
                            />
                          </label>
                          <label className="knowledge-field knowledge-field-wide">
                            <span className="knowledge-label">Answer</span>
                            <Textarea
                              rows={4}
                              value={editDraft.answer}
                              onChange={(event) => setEditDraft((current) => ({ ...current, answer: event.target.value }))}
                            />
                          </label>
                        </div>
                      ) : (
                        <p className="knowledge-card-answer">{entry.answer}</p>
                      )}
                      <span className="knowledge-card-foot">Updated {formatDateTime(entry.updatedAt)}</span>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </section>
      ) : null}

      {activeTab === "gaps" ? (
        <section className="knowledge-shell">
          <section className="knowledge-panel knowledge-panel-list">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Gap review</p>
              <h2 className="panel-title">{loading ? "Loading gaps…" : `${filteredGaps.length} gaps in view`}</h2>
            </div>
            {loading ? (
              <div className="queue-empty">
                <h3 className="empty-title">Loading knowledge gaps…</h3>
              </div>
            ) : filteredGaps.length === 0 ? (
              <div className="queue-empty">
                <h3 className="empty-title">No gaps match this slice.</h3>
                <p className="empty-copy">Try switching between unresolved and resolved gaps, or clear your filters.</p>
              </div>
            ) : (
              <div className="knowledge-list">
                {filteredGaps.map((gap) => {
                  const draft = gapDraftFor(gap.id);
                  const busy = gapBusyId === gap.id;
                  return (
                    <article key={gap.id} className="knowledge-card knowledge-card-gap">
                      <div className="knowledge-card-head">
                        <div>
                          <h3 className="knowledge-card-title">{gap.question}</h3>
                          <p className="knowledge-card-meta">
                            <span>{gap.category}</span>
                            <span>·</span>
                            <span>{gap.property}</span>
                            <span>·</span>
                            <span>{gap.askCount} asks</span>
                            <span>·</span>
                            <span>{formatPercent(gap.confidence)}</span>
                          </p>
                        </div>
                      </div>
                      <div className="knowledge-gap-detail">
                        {gap.reason ? <p><strong>Reason:</strong> {gap.reason}</p> : null}
                        {gap.missingTopics?.length ? <p><strong>Missing topics:</strong> {gap.missingTopics.join(", ")}</p> : null}
                        {gap.aiAnswer ? <p><strong>AI draft:</strong> {gap.aiAnswer}</p> : null}
                        <p><strong>Last asked:</strong> {formatDateTime(gap.lastAskedAt || gap.createdAt)}</p>
                      </div>
                      {!gap.resolved ? (
                        <div className="knowledge-form-grid">
                          <label className="knowledge-field knowledge-field-wide">
                            <span className="knowledge-label">Answer to promote</span>
                            <Textarea
                              rows={4}
                              value={draft.answer}
                              onChange={(event) =>
                                setGapDrafts((current) => ({
                                  ...current,
                                  [gap.id]: { ...gapDraftFor(gap.id), answer: event.target.value },
                                }))
                              }
                              placeholder="Type the answer that should teach the AI here."
                            />
                          </label>
                          <label className="knowledge-field knowledge-field-wide">
                            <span className="knowledge-label">Resolution notes</span>
                            <Input
                              value={draft.notes}
                              onChange={(event) =>
                                setGapDrafts((current) => ({
                                  ...current,
                                  [gap.id]: { ...gapDraftFor(gap.id), notes: event.target.value },
                                }))
                              }
                              placeholder="Optional operator note"
                            />
                          </label>
                          <label className="knowledge-checkbox">
                            <Checkbox
                              checked={draft.addToKb}
                              onChange={(event) =>
                                setGapDrafts((current) => ({
                                  ...current,
                                  [gap.id]: { ...gapDraftFor(gap.id), addToKb: event.target.checked },
                                }))
                              }
                            />
                            <span>Add this answer to the KB when resolving</span>
                          </label>
                          <div className="knowledge-actions">
                            <Button type="button" size="sm" disabled={busy} onClick={() => void handleResolveGap(gap)}>
                              {busy ? "Resolving…" : "Resolve"}
                            </Button>
                            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void handleDismissGap(gap.id)}>
                              Dismiss
                            </Button>
                          </div>
                        </div>
                      ) : (
                        <span className="knowledge-card-foot">Resolved · {formatDateTime(gap.createdAt)}</span>
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </section>
      ) : null}

      {activeTab === "proposals" ? (
        <section className="knowledge-shell">
          <section className="knowledge-panel knowledge-panel-list">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Learned from your edits</p>
              <h2 className="panel-title">
                {loading ? "Loading proposals…" : `${proposals.length} proposal${proposals.length === 1 ? "" : "s"} to review`}
              </h2>
            </div>
            {loading ? (
              <div className="queue-empty">
                <h3 className="empty-title">Loading proposals…</h3>
              </div>
            ) : proposals.length === 0 ? (
              <div className="queue-empty">
                <h3 className="empty-title">No proposals yet.</h3>
                <p className="empty-copy">
                  When you edit an AI draft in a way that changes a fact, policy, or price, that edit shows up
                  here as a proposed knowledge addition you can promote.
                </p>
              </div>
            ) : (
              <div className="knowledge-list">
                {proposals.map((proposal) => {
                  const draft = proposalDraftFor(proposal);
                  const busy = proposalBusyId === proposal.candidateId;
                  return (
                    <article key={proposal.candidateId} className="knowledge-card">
                      <div className="knowledge-card-head">
                        <div>
                          <h3 className="knowledge-card-title">{proposal.proposedQuestion || "Proposed knowledge"}</h3>
                          <p className="knowledge-card-meta">
                            {proposal.editType ? <><span>{proposal.editType.replace(/_/g, " ")}</span><span>·</span></> : null}
                            <span>{formatPercent(proposal.confidence)}</span>
                            <span>·</span>
                            <span>{formatDateTime(proposal.createdAt)}</span>
                          </p>
                        </div>
                      </div>

                      {/* Before / after so the operator sees exactly what changed */}
                      {proposal.originalDraft ? (
                        <div className="knowledge-gap-detail">
                          <p><strong>Original draft:</strong> {proposal.originalDraft}</p>
                        </div>
                      ) : null}

                      <div className="knowledge-form-grid">
                        <label className="knowledge-field knowledge-field-wide">
                          <span className="knowledge-label">Knowledge to promote</span>
                          <Textarea
                            rows={4}
                            value={draft.answer}
                            onChange={(event) => setProposalDraft(proposal.candidateId, { answer: event.target.value }, draft)}
                            placeholder="The answer the AI should learn."
                          />
                        </label>
                        <label className="knowledge-field">
                          <span className="knowledge-label">Apply to</span>
                          <Select
                            value={draft.scope}
                            onChange={(event) =>
                              setProposalDraft(
                                proposal.candidateId,
                                { scope: event.target.value as ProposalScope },
                                draft,
                              )
                            }
                          >
                            <option value="property">This property</option>
                            <option value="property_group">A property group</option>
                            <option value="tenant">All properties (company-wide)</option>
                          </Select>
                        </label>
                        {draft.scope === "property" ? (
                          <label className="knowledge-field">
                            <span className="knowledge-label">Property</span>
                            <Select
                              value={draft.scopeTargetId}
                              onChange={(event) =>
                                setProposalDraft(proposal.candidateId, { scopeTargetId: event.target.value }, draft)
                              }
                            >
                              <option value="">Select…</option>
                              {propertyOptions.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </Select>
                          </label>
                        ) : draft.scope === "property_group" ? (
                          <label className="knowledge-field">
                            <span className="knowledge-label">Group</span>
                            <Select
                              value={draft.scopeTargetId}
                              onChange={(event) =>
                                setProposalDraft(proposal.candidateId, { scopeTargetId: event.target.value }, draft)
                              }
                              disabled={propertyGroups.length === 0}
                            >
                              <option value="">
                                {propertyGroups.length === 0 ? "No groups defined" : "Select…"}
                              </option>
                              {propertyGroups.map((group) => (
                                <option key={group.id} value={group.id}>
                                  {group.name}
                                </option>
                              ))}
                            </Select>
                          </label>
                        ) : null}
                      </div>

                      <div className="knowledge-actions">
                        <Button type="button" size="sm" disabled={busy} onClick={() => void handleApproveProposal(proposal)}>
                          {busy ? "Promoting…" : "Approve & promote"}
                        </Button>
                        <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void handleRejectProposal(proposal)}>
                          Reject
                        </Button>
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        </section>
      ) : null}

      {activeTab === "guidance" ? (
        <section className="knowledge-shell">
          <section className="knowledge-panel knowledge-panel-form">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Operator guidance</p>
              <h2 className="panel-title">Shape the AI without changing the KB</h2>
            </div>
            <label className="knowledge-field knowledge-field-wide">
              <span className="knowledge-label">
                Guidance text
                <span className="knowledge-inline-meta">{guidanceDraft.length}/{guidance.charLimit}</span>
              </span>
              <Textarea
                rows={12}
                value={guidanceDraft}
                onChange={(event) => setGuidanceDraft(event.target.value)}
                placeholder="Example: Keep replies concise, warm, and specific. Never promise early check-in unless explicitly confirmed."
              />
            </label>
            <div className="knowledge-actions">
              <Button
                type="button"
                size="sm"
                disabled={saveGuidanceMutation.isPending}
                onClick={() => void handleSaveGuidance()}
              >
                {saveGuidanceMutation.isPending ? "Saving…" : "Save guidance"}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={saveGuidanceMutation.isPending}
                onClick={() => setGuidanceDraft(guidance.guidanceText || "")}
              >
                Reset
              </Button>
            </div>
            <p className="knowledge-card-foot">
              Last updated {formatDateTime(guidance.updatedAt)}{guidance.updatedBy ? ` by ${guidance.updatedBy}` : ""}
            </p>
          </section>

          <section className="knowledge-panel knowledge-panel-test">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Live check</p>
              <h2 className="panel-title">Test whether the KB would answer cleanly</h2>
            </div>
            <div className="knowledge-test-row">
              <Input
                value={testQuestion}
                onChange={(event) => setTestQuestion(event.target.value)}
                placeholder="Ask a real guest-style question"
              />
              <Button
                type="button"
                variant="secondary"
                size="sm"
                disabled={testQuestionMutation.isPending}
                onClick={() => void handleRunTest()}
              >
                {testQuestionMutation.isPending ? "Testing…" : "Run test"}
              </Button>
            </div>
            {testResult ? (
              <div className={`knowledge-test-result ${testResult.answered ? "is-answered" : "is-gap"}`}>
                <strong>
                  {testResult.answered
                    ? `Matched at ${formatPercent(testResult.confidence)}`
                    : `No confident match (${formatPercent(testResult.confidence)})`}
                </strong>
                <p>{testResult.answer}</p>
                {testResult.sources?.length ? <span>{testResult.sources.join(" · ")}</span> : null}
              </div>
            ) : null}
          </section>
        </section>
      ) : null}
    </main>
  );
}
