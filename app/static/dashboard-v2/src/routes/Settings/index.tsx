import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { SurfaceControls } from "../../components/system/SurfaceControls";
import { SurfaceErrorState } from "../../components/system/SurfaceErrorState";
import { SurfaceHeader } from "../../components/system/SurfaceHeader";
import { SurfaceTabs } from "../../components/system/SurfaceTabs";
import { Button } from "../../components/ui/button";
import { AutonomyTab } from "./AutonomyTab";
import { AlertRoutingTab } from "./AlertRoutingTab";
import { PortfoliosTab } from "./PortfoliosTab";
import { TeamTab } from "./TeamTab";
import { queryKeys } from "../../lib/query/queryKeys";
import {
  useCreateAlertContactMutation,
  useCreatePortfolioMutation,
  useDeleteAlertContactMutation,
  useInviteTeamMemberMutation,
  useMarkAlertContactAvailableMutation,
  useMarkAlertContactOOOMutation,
  useRemoveTeamMemberMutation,
  useSaveSettingsAutonomyMutation,
  useSaveSettingsMutation,
  useUpdateAlertContactMutation,
  useUpdatePortfolioPropertiesMutation,
  useUpdateTeamMemberRoleMutation,
  useUpdateTeamMemberScopesMutation,
} from "../../domain/settings/mutations";
import {
  settingsAlertRoutingQueryOptions,
  settingsAutonomyQueryOptions,
  settingsBaseQueryOptions,
  settingsPortfoliosBundleQueryOptions,
  settingsTeamBundleQueryOptions,
} from "../../domain/settings/queries";
import { useUrlState } from "../../shared/url-state/useUrlState";
import type {
  AlertContact,
  AlertCoverage,
  Portfolio,
  PropertyOption,
  SettingsDraft,
  TeamMember,
  TeamScope,
} from "./types";

const DEFAULTS = {
  tab: "autonomy",
};

type SettingsTab = "autonomy" | "alert_routing" | "team" | "portfolios" | "ai_guidance";

const ALERT_CONTACT_DEFAULT = {
  alertType: "general",
  propertyCode: "",
  contactName: "",
  contactPhone: "",
  contactEmail: "",
  escalationOrder: 1,
  timeoutMinutes: 30,
  activeHoursStart: "",
  activeHoursEnd: "",
  notes: "",
  isPrimary: true,
};

const INVITE_DEFAULT = {
  name: "",
  email: "",
  role: "manager",
};

const PORTFOLIO_DEFAULT = {
  portfolioKey: "",
  displayName: "",
  description: "",
  propertyExternalIds: [] as string[],
};

const SCOPE_DEFAULT = (): TeamScope => ({
  scope_type: "property",
  portfolio_id: "",
  property_external_id: "",
  can_view: true,
  can_assign: false,
  can_manage_vendors: false,
  can_manage_settings: false,
});

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

function formatDate(value?: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleDateString([], {
    month: "short",
    day: "numeric",
  });
}

function slugify(value: string): string {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 50);
}

function propertyLabelByExternalId(propertyOptions: PropertyOption[], externalId: string): string {
  const match = propertyOptions.find((option) => option.externalId === externalId);
  return match?.label || externalId || "Property";
}

export default function SettingsRoute() {
  const queryClient = useQueryClient();
  const [urlState, setUrlState] = useUrlState(DEFAULTS);
  const activeTab = (urlState.tab || "autonomy") as SettingsTab;

  const [error, setError] = useState<Error | null>(null);

  const [settingsDraft, setSettingsDraft] = useState<SettingsDraft | null>(null);
  const [alertDraft, setAlertDraft] = useState(ALERT_CONTACT_DEFAULT);

  const [inviteDraft, setInviteDraft] = useState(INVITE_DEFAULT);
  const [editingScopesFor, setEditingScopesFor] = useState("");
  const [scopeDrafts, setScopeDrafts] = useState<TeamScope[]>([]);

  const [portfolioDraft, setPortfolioDraft] = useState(PORTFOLIO_DEFAULT);
  const [editingPortfolioId, setEditingPortfolioId] = useState("");
  const [editingPortfolioProperties, setEditingPortfolioProperties] = useState<string[]>([]);

  const [busyId, setBusyId] = useState("");
  const saveAutonomyMutation = useSaveSettingsAutonomyMutation();
  const saveSettingsMutation = useSaveSettingsMutation();
  const createAlertContactMutation = useCreateAlertContactMutation();
  const updateAlertContactMutation = useUpdateAlertContactMutation();
  const markAlertOOOMutation = useMarkAlertContactOOOMutation();
  const markAlertAvailableMutation = useMarkAlertContactAvailableMutation();
  const deleteAlertContactMutation = useDeleteAlertContactMutation();
  const inviteTeamMemberMutation = useInviteTeamMemberMutation();
  const updateTeamRoleMutation = useUpdateTeamMemberRoleMutation();
  const removeTeamMemberMutation = useRemoveTeamMemberMutation();
  const updateTeamScopesMutation = useUpdateTeamMemberScopesMutation();
  const createPortfolioMutation = useCreatePortfolioMutation();
  const updatePortfolioPropertiesMutation = useUpdatePortfolioPropertiesMutation();
  const baseQuery = useQuery({
    ...settingsBaseQueryOptions(),
    enabled: activeTab === "autonomy",
  });
  const autonomyQuery = useQuery({
    ...settingsAutonomyQueryOptions(),
    enabled: activeTab === "autonomy",
  });
  const alertRoutingQuery = useQuery({
    ...settingsAlertRoutingQueryOptions(),
    enabled: activeTab === "alert_routing",
  });
  const teamBundleQuery = useQuery({
    ...settingsTeamBundleQueryOptions(),
    enabled: activeTab === "team",
  });
  const portfoliosBundleQuery = useQuery({
    ...settingsPortfoliosBundleQueryOptions(),
    enabled: activeTab === "portfolios",
  });

  const settingsData = baseQuery.data ?? null;
  const autonomyState = autonomyQuery.data ?? null;
  const alertContacts = (alertRoutingQuery.data?.contacts as AlertContact[] | undefined) ?? [];
  const alertCoverage = (alertRoutingQuery.data?.coverage as AlertCoverage[] | undefined) ?? [];
  const alertProperties = (alertRoutingQuery.data?.properties as PropertyOption[] | undefined) ?? [];
  const alertTypes = alertRoutingQuery.data?.alertTypes ?? [];
  const teamMembers = (teamBundleQuery.data?.members as TeamMember[] | undefined) ?? [];
  const memberScopes = (teamBundleQuery.data?.memberScopes as Record<string, TeamScope[]> | undefined) ?? {};
  const portfolios =
    ((activeTab === "team" ? teamBundleQuery.data?.portfolios : portfoliosBundleQuery.data?.portfolios) as Portfolio[] | undefined) ?? [];
  const propertyOptions =
    ((activeTab === "team" ? teamBundleQuery.data?.propertyOptions : portfoliosBundleQuery.data?.propertyOptions) as PropertyOption[] | undefined) ?? [];
  const loading =
    baseQuery.isLoading ||
    autonomyQuery.isLoading ||
    alertRoutingQuery.isLoading ||
    teamBundleQuery.isLoading ||
    portfoliosBundleQuery.isLoading;
  const currentError =
    error ||
    (baseQuery.error as Error | null) ||
    (autonomyQuery.error as Error | null) ||
    (alertRoutingQuery.error as Error | null) ||
    (teamBundleQuery.error as Error | null) ||
    (portfoliosBundleQuery.error as Error | null) ||
    null;

  useEffect(() => {
    if (settingsData) {
      setSettingsDraft(settingsData.settings);
    }
  }, [settingsData]);

  const autonomyDraft = useMemo(() => ({
    autoEnabled: autonomyState?.tenant?.auto_enabled !== false,
    confidenceThreshold: Number(autonomyState?.tenant?.confidence_threshold ?? 0.95),
    lastChangedAt: autonomyState?.tenant?.last_changed_at || null,
  }), [autonomyState]);

  const scopeSummary = useMemo(() => {
    return teamMembers.map((member) => {
      const scopes = memberScopes[member.id] || [];
      const portfoliosCount = scopes.filter((scope) => scope.scope_type === "portfolio").length;
      const propertiesCount = scopes.filter((scope) => scope.scope_type === "property").length;
      const tenantWide = scopes.some((scope) => scope.scope_type === "tenant");
      return {
        memberId: member.id,
        text: tenantWide
          ? "Entire operator visibility"
          : `${portfoliosCount} portfolio scopes · ${propertiesCount} property scopes`,
      };
    });
  }, [memberScopes, teamMembers]);

  async function refreshSettingsTab(tab: SettingsTab = activeTab) {
    if (tab === "autonomy") {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.settings.base() }),
        queryClient.invalidateQueries({ queryKey: queryKeys.autonomy.current() }),
      ]);
      return;
    }
    if (tab === "alert_routing") {
      await queryClient.invalidateQueries({ queryKey: queryKeys.settings.alertRouting() });
      return;
    }
    if (tab === "team") {
      await queryClient.invalidateQueries({ queryKey: queryKeys.settings.team() });
      return;
    }
    if (tab === "portfolios") {
      await queryClient.invalidateQueries({ queryKey: queryKeys.settings.portfolios() });
    }
  }

  function mutateSettings<K extends keyof SettingsDraft>(key: K, value: SettingsDraft[K]) {
    setSettingsDraft((current) => (current ? { ...current, [key]: value } : current));
  }

  function mutateNestedSettings(section: "proactivePolicy" | "escalationGuestPolicy" | "stayOperationsPolicy" | "retentionPolicy", key: string, value: any) {
    setSettingsDraft((current) => {
      if (!current) return current;
      return {
        ...current,
        [section]: {
          ...current[section],
          [key]: value,
        },
      };
    });
  }

  async function handleSaveAutonomy() {
    setBusyId("autonomy");
    setError(null);
    try {
      const payload = await saveAutonomyMutation.mutateAsync({
        auto_enabled: autonomyDraft.autoEnabled,
        confidence_threshold: autonomyDraft.confidenceThreshold,
      });
      queryClient.setQueryData(queryKeys.autonomy.current(), payload);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to save autonomy"));
    } finally {
      setBusyId("");
    }
  }

  async function handleSaveSettings() {
    if (!settingsDraft) return;
    setBusyId("settings");
    setError(null);
    try {
      await saveSettingsMutation.mutateAsync({
        ai_concierge_name: settingsDraft.aiConciergeName,
        notify_emergency: settingsDraft.notifyEmergency,
        notify_maintenance: settingsDraft.notifyMaintenance,
        notify_prebooking: settingsDraft.notifyPrebooking,
        notify_kb_gaps: settingsDraft.notifyKbGaps,
        notify_weekly_analytics: settingsDraft.notifyWeeklyAnalytics,
        proactive_policy: {
          enabled_touch_types: settingsDraft.proactivePolicy.enabledTouchTypes,
          min_hours_between_proactive_touches: settingsDraft.proactivePolicy.minHoursBetweenProactiveTouches,
          min_hours_between_service_updates: settingsDraft.proactivePolicy.minHoursBetweenServiceUpdates,
          max_notifications_per_stay_window: settingsDraft.proactivePolicy.maxNotificationsPerStayWindow,
          allow_service_updates_during_escalation: settingsDraft.proactivePolicy.allowServiceUpdatesDuringEscalation,
        },
        escalation_guest_policy: {
          allow_eta_updates: settingsDraft.escalationGuestPolicy.allowEtaUpdates,
          allow_reassurance_without_eta: settingsDraft.escalationGuestPolicy.allowReassuranceWithoutEta,
          operator_approval_required_for_status_updates:
            settingsDraft.escalationGuestPolicy.operatorApprovalRequiredForStatusUpdates,
        },
        stay_operations_policy: {
          workflow_profile: settingsDraft.stayOperationsPolicy.workflowProfile,
          enable_access_workflows: settingsDraft.stayOperationsPolicy.enableAccessWorkflows,
          enable_rental_workflows: settingsDraft.stayOperationsPolicy.enableRentalWorkflows,
          enable_turnover_workflows: settingsDraft.stayOperationsPolicy.enableTurnoverWorkflows,
          enable_maintenance_workflows: settingsDraft.stayOperationsPolicy.enableMaintenanceWorkflows,
          enable_post_checkout_walkthrough: settingsDraft.stayOperationsPolicy.enablePostCheckoutWalkthrough,
          walkthrough_required_before_ready: settingsDraft.stayOperationsPolicy.walkthroughRequiredBeforeReady,
          auto_archive_when_turnover_ready: settingsDraft.stayOperationsPolicy.autoArchiveWhenTurnoverReady,
        },
        retention_policy: {
          active_search_window_days: settingsDraft.retentionPolicy.activeSearchWindowDays,
          post_stay_follow_up_days: settingsDraft.retentionPolicy.postStayFollowUpDays,
          raw_guest_content_retention_days: settingsDraft.retentionPolicy.rawGuestContentRetentionDays,
          pre_booking_record_retention_days: settingsDraft.retentionPolicy.preBookingRecordRetentionDays,
          guest_session_shell_retention_days: settingsDraft.retentionPolicy.guestSessionShellRetentionDays,
          structured_signal_retention_days: settingsDraft.retentionPolicy.structuredSignalRetentionDays,
          auto_cleanup_enabled: settingsDraft.retentionPolicy.autoCleanupEnabled,
          preserve_guest_identity: settingsDraft.retentionPolicy.preserveGuestIdentity,
        },
      });
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to save settings"));
    } finally {
      setBusyId("");
    }
  }

  async function handleCreateAlertContact() {
    if (!alertDraft.contactName.trim()) return;
    setBusyId("alert-create");
    setError(null);
    try {
      await createAlertContactMutation.mutateAsync({
        alert_type: alertDraft.alertType,
        property_code: alertDraft.propertyCode,
        contact_name: alertDraft.contactName.trim(),
        contact_phone: alertDraft.contactPhone.trim(),
        contact_email: alertDraft.contactEmail.trim(),
        escalation_order: Number(alertDraft.escalationOrder) || 1,
        escalation_timeout_minutes: Number(alertDraft.timeoutMinutes) || 30,
        active_hours_start: alertDraft.activeHoursStart || null,
        active_hours_end: alertDraft.activeHoursEnd || null,
        notes: alertDraft.notes.trim(),
        is_primary: alertDraft.isPrimary,
      });
      setAlertDraft(ALERT_CONTACT_DEFAULT);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to create alert contact"));
    } finally {
      setBusyId("");
    }
  }

  async function handleUpdateAlertContact(contact: AlertContact) {
    setBusyId(`alert-${contact.id}`);
    setError(null);
    try {
      await updateAlertContactMutation.mutateAsync({ contactId: contact.id, body: {
        contact_name: contact.contactName.trim(),
        contact_phone: contact.contactPhone.trim(),
        contact_email: contact.contactEmail.trim(),
        alert_type: contact.alertType,
        property_code: contact.propertyCode || "",
        is_primary: contact.isPrimary,
        escalation_order: Number(contact.escalationOrder) || 1,
        escalation_timeout_minutes: Number(contact.timeoutMinutes) || 30,
        notes: contact.notes.trim(),
      } });
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to update alert contact"));
    } finally {
      setBusyId("");
    }
  }

  async function handleToggleAvailability(contact: AlertContact) {
    setBusyId(`alert-status-${contact.id}`);
    setError(null);
    try {
      if (contact.isAvailable) {
        const until = new Date(Date.now() + 4 * 60 * 60 * 1000).toISOString();
        await markAlertOOOMutation.mutateAsync({ contactId: contact.id, body: {
          unavailable_until: until,
          redirect_to_id: contact.redirectToId || null,
        } });
      } else {
        await markAlertAvailableMutation.mutateAsync(contact.id);
      }
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to update availability"));
    } finally {
      setBusyId("");
    }
  }

  async function handleDeleteAlertContact(contactId: string) {
    setBusyId(`alert-delete-${contactId}`);
    setError(null);
    try {
      await deleteAlertContactMutation.mutateAsync(contactId);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to delete alert contact"));
    } finally {
      setBusyId("");
    }
  }

  async function handleInviteMember() {
    if (!inviteDraft.name.trim() || !inviteDraft.email.trim()) return;
    setBusyId("invite");
    setError(null);
    try {
      await inviteTeamMemberMutation.mutateAsync({
        name: inviteDraft.name.trim(),
        email: inviteDraft.email.trim(),
        role: inviteDraft.role,
      });
      setInviteDraft(INVITE_DEFAULT);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to invite team member"));
    } finally {
      setBusyId("");
    }
  }

  async function handleUpdateRole(memberId: string, role: string) {
    setBusyId(`role-${memberId}`);
    setError(null);
    try {
      await updateTeamRoleMutation.mutateAsync({ memberId, role });
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to update role"));
    } finally {
      setBusyId("");
    }
  }

  async function handleRemoveMember(memberId: string) {
    setBusyId(`member-delete-${memberId}`);
    setError(null);
    try {
      await removeTeamMemberMutation.mutateAsync(memberId);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to remove team member"));
    } finally {
      setBusyId("");
    }
  }

  async function beginScopeEdit(memberId: string) {
    setBusyId(`scope-load-${memberId}`);
    try {
      const scopes = memberScopes[memberId] || [];
      setEditingScopesFor(memberId);
      setScopeDrafts(scopes.length ? scopes : [SCOPE_DEFAULT()]);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to load scopes"));
    } finally {
      setBusyId("");
    }
  }

  async function handleSaveScopes(memberId: string) {
    setBusyId(`scope-save-${memberId}`);
    setError(null);
    try {
      await updateTeamScopesMutation.mutateAsync({ memberId, scopes: scopeDrafts });
      setEditingScopesFor("");
      setScopeDrafts([]);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to save scopes"));
    } finally {
      setBusyId("");
    }
  }

  async function handleCreatePortfolio() {
    if (!portfolioDraft.displayName.trim()) return;
    setBusyId("portfolio-create");
    setError(null);
    try {
      const created = await createPortfolioMutation.mutateAsync({
        portfolio_key: slugify(portfolioDraft.portfolioKey || portfolioDraft.displayName),
        display_name: portfolioDraft.displayName.trim(),
        description: portfolioDraft.description.trim(),
      });
      await updatePortfolioPropertiesMutation.mutateAsync({
        portfolioId: String(created.portfolio_id || ""),
        propertyExternalIds: portfolioDraft.propertyExternalIds,
      });
      setPortfolioDraft(PORTFOLIO_DEFAULT);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to create portfolio"));
    } finally {
      setBusyId("");
    }
  }

  async function handleSavePortfolioProperties(portfolioId: string) {
    setBusyId(`portfolio-save-${portfolioId}`);
    setError(null);
    try {
      await updatePortfolioPropertiesMutation.mutateAsync({
        portfolioId,
        propertyExternalIds: editingPortfolioProperties,
      });
      setEditingPortfolioId("");
      setEditingPortfolioProperties([]);
    } catch (nextError: any) {
      setError(nextError instanceof Error ? nextError : new Error("Failed to update portfolio"));
    } finally {
      setBusyId("");
    }
  }

  function togglePortfolioProperty(propertyExternalId: string, checked: boolean, mode: "draft" | "edit") {
    const updater = (currentIds: string[]) =>
      checked
        ? Array.from(new Set([...currentIds, propertyExternalId]))
        : currentIds.filter((value) => value !== propertyExternalId);
    if (mode === "draft") {
      setPortfolioDraft((current) => ({
        ...current,
        propertyExternalIds: updater(current.propertyExternalIds),
      }));
    } else {
      setEditingPortfolioProperties((current) => updater(current));
    }
  }

  function renderScopeBadges(scope: TeamScope) {
    const labels = [];
    if (scope.can_view) labels.push("view");
    if (scope.can_assign) labels.push("assign");
    if (scope.can_manage_vendors) labels.push("vendors");
    if (scope.can_manage_settings) labels.push("settings");
    return labels.join(" · ") || "no permissions";
  }

  const tabs = [
    { key: "autonomy", label: "Autonomy" },
    { key: "alert_routing", label: "Alert routing" },
    { key: "team", label: "Team" },
    { key: "portfolios", label: "Portfolios" },
    { key: "ai_guidance", label: "AI guidance" },
  ] as const;

  return (
    <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
      <SurfaceHeader
        title="Settings"
        subtitle="Operator autonomy, routing, team coverage, and portfolio boundaries now point at the live backend."
      />

      <SurfaceControls ariaLabel="Settings tabs">
        <div className="filter-bar settings-tab-bar">
          <SurfaceTabs
            ariaLabel="Settings tabs"
            tabs={tabs.map((tab) => ({ key: tab.key, label: tab.label }))}
            activeKey={activeTab}
            onSelect={(key) => setUrlState({ tab: key }, { replace: true })}
          />
          <Button type="button" variant="secondary" size="sm" onClick={() => void refreshSettingsTab()}>
            Refresh
          </Button>
        </div>
      </SurfaceControls>

      {error ? (
        <SurfaceErrorState
          title="Settings load failed"
          detail={error.message}
          onRetry={() => refreshSettingsTab()}
        />
      ) : null}

      <section className="knowledge-shell">
        {activeTab === "autonomy" ? (
          <AutonomyTab
            autonomyDraft={autonomyDraft}
            busyId={busyId}
            loading={loading}
            settingsData={settingsData}
            settingsDraft={settingsDraft}
            formatDateTime={formatDateTime}
            mutateSettings={mutateSettings}
            mutateNestedSettings={mutateNestedSettings}
            onAutonomyDraftChange={(updater) =>
              queryClient.setQueryData(queryKeys.autonomy.current(), (current: any) => updater(current))
            }
            onSaveAutonomy={handleSaveAutonomy}
            onSaveSettings={handleSaveSettings}
          />
        ) : null}

        {activeTab === "alert_routing" ? (
          <AlertRoutingTab
            alertContacts={alertContacts}
            alertCoverage={alertCoverage}
            alertDraft={alertDraft}
            alertProperties={alertProperties}
            alertTypes={alertTypes}
            busyId={busyId}
            loading={loading}
            onAlertDraftChange={(updater) => setAlertDraft((current) => updater(current))}
            onCreateAlertContact={handleCreateAlertContact}
            onToggleAvailability={handleToggleAvailability}
            onDeleteAlertContact={handleDeleteAlertContact}
            onUpdateAlertContact={handleUpdateAlertContact}
          />
        ) : null}

        {activeTab === "team" ? (
          <TeamTab
            busyId={busyId}
            editingScopesFor={editingScopesFor}
            inviteDraft={inviteDraft}
            loading={loading}
            memberScopes={memberScopes}
            portfolios={portfolios}
            propertyOptions={propertyOptions}
            scopeDrafts={scopeDrafts}
            scopeSummary={scopeSummary}
            teamMembers={teamMembers}
            formatDate={formatDate}
            formatDateTime={formatDateTime}
            propertyLabelByExternalId={propertyLabelByExternalId}
            renderScopeBadges={renderScopeBadges}
            scopeDefaultFactory={SCOPE_DEFAULT}
            onBeginScopeEdit={beginScopeEdit}
            onInviteDraftChange={(updater) => setInviteDraft((current) => updater(current))}
            onInviteMember={handleInviteMember}
            onRemoveMember={handleRemoveMember}
            onSaveScopes={handleSaveScopes}
            onScopeDraftsChange={(updater) => setScopeDrafts((current) => updater(current))}
            onScopeEditorClose={() => setEditingScopesFor("")}
            onUpdateRole={handleUpdateRole}
          />
        ) : null}

        {activeTab === "portfolios" ? (
          <PortfoliosTab
            busyId={busyId}
            editingPortfolioId={editingPortfolioId}
            editingPortfolioProperties={editingPortfolioProperties}
            loading={loading}
            portfolioDraft={portfolioDraft}
            portfolios={portfolios}
            propertyOptions={propertyOptions}
            propertyLabelByExternalId={propertyLabelByExternalId}
            onBeginPortfolioEdit={(portfolioId, propertyExternalIds) => {
              setEditingPortfolioId(portfolioId);
              setEditingPortfolioProperties(propertyExternalIds);
            }}
            onCancelPortfolioEdit={() => setEditingPortfolioId("")}
            onCreatePortfolio={handleCreatePortfolio}
            onPortfolioDraftChange={(updater) => setPortfolioDraft((current) => updater(current))}
            onSavePortfolioProperties={handleSavePortfolioProperties}
            onTogglePortfolioProperty={togglePortfolioProperty}
          />
        ) : null}

        {activeTab === "ai_guidance" ? (
          <section className="knowledge-panel">
            <div className="knowledge-panel-head">
              <p className="panel-kicker">Single source of truth</p>
              <h2 className="panel-title">AI guidance lives in Knowledge</h2>
            </div>
            <div className="knowledge-gap-detail">
              <p>
                The AI guidance editor is already live on the canonical Knowledge surface. We’re keeping it single-homed there so
                Settings does not become a duplicate editor for the same backend.
              </p>
            </div>
            <div className="knowledge-actions">
              <Button asChild size="sm">
                <Link to="/app/v2/knowledge?tab=guidance">Open AI guidance in Knowledge</Link>
              </Button>
            </div>
          </section>
        ) : null}
      </section>
    </main>
  );
}
