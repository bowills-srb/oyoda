import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import type { Portfolio, PropertyOption, TeamMember, TeamScope } from "./types";

type InviteDraft = {
  name: string;
  email: string;
  role: string;
};

type ScopeSummaryItem = {
  memberId: string;
  text: string;
};

type TeamTabProps = {
  busyId: string;
  editingScopesFor: string;
  inviteDraft: InviteDraft;
  loading: boolean;
  memberScopes: Record<string, TeamScope[]>;
  portfolios: Portfolio[];
  propertyOptions: PropertyOption[];
  scopeDrafts: TeamScope[];
  scopeSummary: ScopeSummaryItem[];
  teamMembers: TeamMember[];
  formatDate: (value?: string | null) => string;
  formatDateTime: (value?: string | null) => string;
  propertyLabelByExternalId: (propertyOptions: PropertyOption[], externalId: string) => string;
  renderScopeBadges: (scope: TeamScope) => string;
  scopeDefaultFactory: () => TeamScope;
  onBeginScopeEdit: (memberId: string) => void | Promise<void>;
  onInviteDraftChange: (updater: (current: InviteDraft) => InviteDraft) => void;
  onInviteMember: () => void | Promise<void>;
  onRemoveMember: (memberId: string) => void | Promise<void>;
  onSaveScopes: (memberId: string) => void | Promise<void>;
  onScopeDraftsChange: (updater: (current: TeamScope[]) => TeamScope[]) => void;
  onScopeEditorClose: () => void;
  onUpdateRole: (memberId: string, role: string) => void | Promise<void>;
};

export function TeamTab({
  busyId,
  editingScopesFor,
  inviteDraft,
  loading,
  memberScopes,
  portfolios,
  propertyOptions,
  scopeDrafts,
  scopeSummary,
  teamMembers,
  formatDate,
  formatDateTime,
  propertyLabelByExternalId,
  renderScopeBadges,
  scopeDefaultFactory,
  onBeginScopeEdit,
  onInviteDraftChange,
  onInviteMember,
  onRemoveMember,
  onSaveScopes,
  onScopeDraftsChange,
  onScopeEditorClose,
  onUpdateRole,
}: TeamTabProps) {
  return (
    <>
      <section className="knowledge-panel knowledge-panel-form">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Invite</p>
          <h2 className="panel-title">Add managers and staff</h2>
        </div>
        <div className="knowledge-form-grid">
          <label className="knowledge-field">
            <span className="knowledge-label">Name</span>
            <Input
              value={inviteDraft.name}
              onChange={(event) => onInviteDraftChange((current) => ({ ...current, name: event.target.value }))}
            />
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Email</span>
            <Input
              value={inviteDraft.email}
              onChange={(event) => onInviteDraftChange((current) => ({ ...current, email: event.target.value }))}
            />
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Role</span>
            <Select
              value={inviteDraft.role}
              onChange={(event) => onInviteDraftChange((current) => ({ ...current, role: event.target.value }))}
            >
              <option value="manager">Manager</option>
              <option value="staff">Staff</option>
            </Select>
          </label>
        </div>
        <div className="knowledge-actions">
          <Button type="button" size="sm" disabled={busyId === "invite"} onClick={() => void onInviteMember()}>
            {busyId === "invite" ? "Sending…" : "Send invite"}
          </Button>
        </div>
      </section>

      <section className="knowledge-panel knowledge-panel-list">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Team</p>
          <h2 className="panel-title">{loading ? "Loading team…" : `${teamMembers.length} members in workspace`}</h2>
        </div>
        <div className="knowledge-list">
          {teamMembers.map((member) => (
            <article key={member.id} className="knowledge-card">
              <div className="knowledge-card-head">
                <div>
                  <h3 className="knowledge-card-title">{member.name}</h3>
                  <p className="knowledge-card-meta">
                    <span>{member.email}</span>
                    <span>·</span>
                    <span>{member.role}</span>
                    <span>·</span>
                    <span>{member.activated ? "Active" : "Invited"}</span>
                  </p>
                </div>
                <div className="knowledge-actions">
                  <Select
                    value={member.role}
                    onChange={(event) => void onUpdateRole(member.id, event.target.value)}
                  >
                    <option value="manager">Manager</option>
                    <option value="staff">Staff</option>
                  </Select>
                  <Button type="button" variant="secondary" size="sm" onClick={() => void onBeginScopeEdit(member.id)}>
                    Scope
                  </Button>
                  <Button type="button" variant="ghost" size="sm" onClick={() => void onRemoveMember(member.id)}>
                    Remove
                  </Button>
                </div>
              </div>
              <div className="knowledge-gap-detail">
                <p><strong>Joined:</strong> {formatDate(member.joinedAt)}</p>
                <p><strong>Last login:</strong> {formatDateTime(member.lastLoginAt)}</p>
                <p><strong>Coverage:</strong> {scopeSummary.find((item) => item.memberId === member.id)?.text || "No explicit scope"}</p>
              </div>
              <div className="settings-scope-list">
                {(memberScopes[member.id] || []).map((scope, index) => (
                  <span key={`${member.id}-${index}`} className="settings-chip">
                    {scope.scope_type === "tenant"
                      ? "Entire operator"
                      : scope.scope_type === "portfolio"
                        ? portfolios.find((portfolio) => portfolio.id === scope.portfolio_id)?.displayName || "Portfolio"
                        : propertyLabelByExternalId(propertyOptions, scope.property_external_id)}
                    {" · "}
                    {renderScopeBadges(scope)}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>

      {editingScopesFor ? (
        <section className="knowledge-panel knowledge-panel-form">
          <div className="knowledge-panel-head">
            <p className="panel-kicker">Scope editor</p>
            <h2 className="panel-title">
              Manage scope for {teamMembers.find((member) => member.id === editingScopesFor)?.name || "member"}
            </h2>
          </div>
          <div className="knowledge-list">
            {scopeDrafts.map((scope, index) => (
              <article key={`scope-${index}`} className="knowledge-card">
                <div className="knowledge-form-grid">
                  <label className="knowledge-field">
                    <span className="knowledge-label">Scope type</span>
                    <Select
                      value={scope.scope_type}
                      onChange={(event) =>
                        onScopeDraftsChange((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index
                              ? { ...item, scope_type: event.target.value as TeamScope["scope_type"] }
                              : item,
                          ),
                        )
                      }
                    >
                      <option value="property">Property</option>
                      <option value="portfolio">Portfolio</option>
                      <option value="tenant">Entire operator</option>
                    </Select>
                  </label>
                  <label className="knowledge-field">
                    <span className="knowledge-label">Portfolio</span>
                    <Select
                      value={scope.portfolio_id}
                      onChange={(event) =>
                        onScopeDraftsChange((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, portfolio_id: event.target.value } : item,
                          ),
                        )
                      }
                    >
                      <option value="">Select portfolio</option>
                      {portfolios.map((portfolio) => (
                        <option key={portfolio.id} value={portfolio.id}>
                          {portfolio.displayName}
                        </option>
                      ))}
                    </Select>
                  </label>
                  <label className="knowledge-field">
                    <span className="knowledge-label">Property</span>
                    <Select
                      value={scope.property_external_id}
                      onChange={(event) =>
                        onScopeDraftsChange((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, property_external_id: event.target.value } : item,
                          ),
                        )
                      }
                    >
                      <option value="">Select property</option>
                      {propertyOptions.map((property) => (
                        <option key={property.externalId} value={property.externalId}>
                          {property.label}
                        </option>
                      ))}
                    </Select>
                  </label>
                  <label className="knowledge-checkbox">
                    <Checkbox
                      checked={scope.can_view}
                      onChange={(event) =>
                        onScopeDraftsChange((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, can_view: event.target.checked } : item,
                          ),
                        )
                      }
                    />
                    <span>Can view</span>
                  </label>
                  <label className="knowledge-checkbox">
                    <Checkbox
                      checked={scope.can_assign}
                      onChange={(event) =>
                        onScopeDraftsChange((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, can_assign: event.target.checked } : item,
                          ),
                        )
                      }
                    />
                    <span>Can assign</span>
                  </label>
                  <label className="knowledge-checkbox">
                    <Checkbox
                      checked={scope.can_manage_vendors}
                      onChange={(event) =>
                        onScopeDraftsChange((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, can_manage_vendors: event.target.checked } : item,
                          ),
                        )
                      }
                    />
                    <span>Can manage vendors</span>
                  </label>
                  <label className="knowledge-checkbox">
                    <Checkbox
                      checked={scope.can_manage_settings}
                      onChange={(event) =>
                        onScopeDraftsChange((current) =>
                          current.map((item, itemIndex) =>
                            itemIndex === index ? { ...item, can_manage_settings: event.target.checked } : item,
                          ),
                        )
                      }
                    />
                    <span>Can manage settings</span>
                  </label>
                </div>
                <div className="knowledge-actions">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => onScopeDraftsChange((current) => current.filter((_, itemIndex) => itemIndex !== index))}
                  >
                    Remove scope
                  </Button>
                </div>
              </article>
            ))}
          </div>
          <div className="knowledge-actions">
            <Button type="button" variant="secondary" size="sm" onClick={() => onScopeDraftsChange((current) => [...current, scopeDefaultFactory()])}>
              Add scope
            </Button>
            <Button type="button" size="sm" disabled={busyId === `scope-save-${editingScopesFor}`} onClick={() => void onSaveScopes(editingScopesFor)}>
              {busyId === `scope-save-${editingScopesFor}` ? "Saving…" : "Save scopes"}
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={onScopeEditorClose}>
              Cancel
            </Button>
          </div>
        </section>
      ) : null}
    </>
  );
}
