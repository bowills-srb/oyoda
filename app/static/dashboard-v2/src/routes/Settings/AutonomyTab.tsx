import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Slider } from "../../components/ui/slider";
import { Switch } from "../../components/ui/switch";
import type { SettingsData, SettingsDraft } from "./types";

type AutonomyTenantState = {
  tenant?: {
    auto_enabled?: boolean;
    confidence_threshold?: number;
    last_changed_at?: string | null;
  };
} | null;

type AutonomyTabProps = {
  autonomyDraft: {
    autoEnabled: boolean;
    confidenceThreshold: number;
    lastChangedAt: string | null;
  };
  busyId: string;
  loading: boolean;
  settingsData: SettingsData | null;
  settingsDraft: SettingsDraft | null;
  formatDateTime: (value?: string | null) => string;
  mutateSettings: <K extends keyof SettingsDraft>(key: K, value: SettingsDraft[K]) => void;
  mutateNestedSettings: (
    section: "proactivePolicy" | "escalationGuestPolicy" | "stayOperationsPolicy" | "retentionPolicy",
    key: string,
    value: any,
  ) => void;
  onAutonomyDraftChange: (updater: (current: AutonomyTenantState) => AutonomyTenantState) => void;
  onSaveAutonomy: () => void | Promise<void>;
  onSaveSettings: () => void | Promise<void>;
};

export function AutonomyTab({
  autonomyDraft,
  busyId,
  loading,
  settingsData,
  settingsDraft,
  formatDateTime,
  mutateSettings,
  mutateNestedSettings,
  onAutonomyDraftChange,
  onSaveAutonomy,
  onSaveSettings,
}: AutonomyTabProps) {
  return (
    <>
      <section className="knowledge-panel settings-summary-grid">
        <article className="knowledge-card">
          <p className="panel-kicker">Account</p>
          <h2 className="panel-title">{settingsData?.account.companyName || "Operator account"}</h2>
          <p className="knowledge-card-meta">
            <span>{settingsData?.account.contactEmail || "—"}</span>
            <span>·</span>
            <span>{settingsData?.account.pms || "escapia"}</span>
            <span>·</span>
            <span>{settingsData?.account.propertyCount || 0} properties</span>
          </p>
        </article>
        <article className="knowledge-card">
          <p className="panel-kicker">AI posture</p>
          <h2 className="panel-title">
            {autonomyDraft.autoEnabled ? "Autonomy live" : "Autonomy paused"}
          </h2>
          <p className="knowledge-card-meta">
            <span className="tabular-nums">{Math.round(autonomyDraft.confidenceThreshold * 100)}% threshold</span>
            <span>·</span>
            <span>Last changed {formatDateTime(autonomyDraft.lastChangedAt)}</span>
          </p>
        </article>
      </section>

      <section className="knowledge-panel knowledge-panel-form">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Global autonomy</p>
          <h2 className="panel-title">Canonical pre-booking autonomy controls</h2>
        </div>
        <div className="knowledge-form-grid">
          <label className="knowledge-checkbox">
            <Switch
              checked={autonomyDraft.autoEnabled}
              onCheckedChange={(checked) =>
                onAutonomyDraftChange((current) => ({
                  ...current,
                  tenant: {
                    ...(current?.tenant || {}),
                    auto_enabled: checked,
                  },
                }))
              }
            />
            <span>Enable autonomy-driven auto-send</span>
          </label>
          <label className="knowledge-field knowledge-field-wide">
            <span className="knowledge-label">
              Confidence threshold
              <span className="knowledge-inline-meta tabular-nums">
                {Math.round(autonomyDraft.confidenceThreshold * 100)}%
              </span>
            </span>
            <Slider
              min={0.5}
              max={0.99}
              step={0.01}
              value={autonomyDraft.confidenceThreshold}
              onChange={(event) =>
                onAutonomyDraftChange((current) => ({
                  ...current,
                  tenant: {
                    ...(current?.tenant || {}),
                    confidence_threshold: Number(event.target.value),
                  },
                }))
              }
            />
          </label>
        </div>
        <div className="knowledge-actions">
          <Button type="button" size="sm" disabled={busyId === "autonomy"} onClick={() => void onSaveAutonomy()}>
            {busyId === "autonomy" ? "Saving…" : "Save autonomy"}
          </Button>
        </div>
      </section>

      <section className="knowledge-panel knowledge-panel-form">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Operator policy</p>
          <h2 className="panel-title">{loading ? "Loading settings…" : "Messaging and retention settings"}</h2>
        </div>
        {settingsDraft ? (
          <>
            <div className="knowledge-form-grid">
              <label className="knowledge-field">
                <span className="knowledge-label">AI concierge name</span>
                <Input
                  value={settingsDraft.aiConciergeName}
                  onChange={(event) => mutateSettings("aiConciergeName", event.target.value)}
                />
              </label>
              <label className="knowledge-checkbox">
                <Checkbox
                  checked={settingsDraft.notifyEmergency}
                  onChange={(event) => mutateSettings("notifyEmergency", event.target.checked)}
                />
                <span>Notify emergency alerts</span>
              </label>
              <label className="knowledge-checkbox">
                <Checkbox
                  checked={settingsDraft.notifyMaintenance}
                  onChange={(event) => mutateSettings("notifyMaintenance", event.target.checked)}
                />
                <span>Notify maintenance alerts</span>
              </label>
              <label className="knowledge-checkbox">
                <Checkbox
                  checked={settingsDraft.notifyPrebooking}
                  onChange={(event) => mutateSettings("notifyPrebooking", event.target.checked)}
                />
                <span>Notify pre-booking queue</span>
              </label>
              <label className="knowledge-checkbox">
                <Checkbox
                  checked={settingsDraft.notifyKbGaps}
                  onChange={(event) => mutateSettings("notifyKbGaps", event.target.checked)}
                />
                <span>Notify knowledge gaps</span>
              </label>
              <label className="knowledge-checkbox">
                <Checkbox
                  checked={settingsDraft.notifyWeeklyAnalytics}
                  onChange={(event) => mutateSettings("notifyWeeklyAnalytics", event.target.checked)}
                />
                <span>Notify weekly analytics</span>
              </label>
              <label className="knowledge-field">
                <span className="knowledge-label">Workflow profile</span>
                <Select
                  value={settingsDraft.stayOperationsPolicy.workflowProfile}
                  onChange={(event) =>
                    mutateNestedSettings("stayOperationsPolicy", "workflowProfile", event.target.value)
                  }
                >
                  <option value="messaging_only">Messaging only</option>
                  <option value="assisted_ops">Assisted ops</option>
                  <option value="full_ops">Full ops</option>
                </Select>
              </label>
              <label className="knowledge-field">
                <span className="knowledge-label">Min hours between proactive touches</span>
                <Input
                  type="number"
                  min={1}
                  value={settingsDraft.proactivePolicy.minHoursBetweenProactiveTouches}
                  onChange={(event) =>
                    mutateNestedSettings(
                      "proactivePolicy",
                      "minHoursBetweenProactiveTouches",
                      Number(event.target.value) || 18,
                    )
                  }
                />
              </label>
              <label className="knowledge-field">
                <span className="knowledge-label">Max notifications per stay</span>
                <Input
                  type="number"
                  min={1}
                  value={settingsDraft.proactivePolicy.maxNotificationsPerStayWindow}
                  onChange={(event) =>
                    mutateNestedSettings(
                      "proactivePolicy",
                      "maxNotificationsPerStayWindow",
                      Number(event.target.value) || 6,
                    )
                  }
                />
              </label>
              <label className="knowledge-field">
                <span className="knowledge-label">Raw guest retention days</span>
                <Input
                  type="number"
                  min={1}
                  value={settingsDraft.retentionPolicy.rawGuestContentRetentionDays}
                  onChange={(event) =>
                    mutateNestedSettings(
                      "retentionPolicy",
                      "rawGuestContentRetentionDays",
                      Number(event.target.value) || 90,
                    )
                  }
                />
              </label>
              <label className="knowledge-field">
                <span className="knowledge-label">Structured signal retention days</span>
                <Input
                  type="number"
                  min={1}
                  value={settingsDraft.retentionPolicy.structuredSignalRetentionDays}
                  onChange={(event) =>
                    mutateNestedSettings(
                      "retentionPolicy",
                      "structuredSignalRetentionDays",
                      Number(event.target.value) || 365,
                    )
                  }
                />
              </label>
              <label className="knowledge-checkbox">
                <Checkbox
                  checked={settingsDraft.retentionPolicy.autoCleanupEnabled}
                  onChange={(event) =>
                    mutateNestedSettings("retentionPolicy", "autoCleanupEnabled", event.target.checked)
                  }
                />
                <span>Enable auto cleanup</span>
              </label>
              <label className="knowledge-checkbox">
                <Checkbox
                  checked={settingsDraft.retentionPolicy.preserveGuestIdentity}
                  onChange={(event) =>
                    mutateNestedSettings("retentionPolicy", "preserveGuestIdentity", event.target.checked)
                  }
                />
                <span>Preserve guest identity</span>
              </label>
            </div>
            <div className="knowledge-actions">
              <Button type="button" size="sm" disabled={busyId === "settings"} onClick={() => void onSaveSettings()}>
                {busyId === "settings" ? "Saving…" : "Save settings"}
              </Button>
            </div>
          </>
        ) : (
          <div className="queue-empty">
            <h3 className="empty-title">Loading settings…</h3>
          </div>
        )}
      </section>
    </>
  );
}
