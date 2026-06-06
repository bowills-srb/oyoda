import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";
import { Textarea } from "../../components/ui/textarea";
import type { AlertContact, AlertCoverage, PropertyOption } from "./types";

type AlertDraft = {
  alertType: string;
  propertyCode: string;
  contactName: string;
  contactPhone: string;
  contactEmail: string;
  escalationOrder: number;
  timeoutMinutes: number;
  activeHoursStart: string;
  activeHoursEnd: string;
  notes: string;
  isPrimary: boolean;
};

type AlertRoutingTabProps = {
  alertContacts: AlertContact[];
  alertCoverage: AlertCoverage[];
  alertDraft: AlertDraft;
  alertProperties: PropertyOption[];
  alertTypes: string[];
  busyId: string;
  loading: boolean;
  onAlertDraftChange: (updater: (current: AlertDraft) => AlertDraft) => void;
  onCreateAlertContact: () => void | Promise<void>;
  onToggleAvailability: (contact: AlertContact) => void | Promise<void>;
  onDeleteAlertContact: (contactId: string) => void | Promise<void>;
  onUpdateAlertContact: (contact: AlertContact) => void | Promise<void>;
};

export function AlertRoutingTab({
  alertContacts,
  alertCoverage,
  alertDraft,
  alertProperties,
  alertTypes,
  busyId,
  loading,
  onAlertDraftChange,
  onCreateAlertContact,
  onToggleAvailability,
  onDeleteAlertContact,
  onUpdateAlertContact,
}: AlertRoutingTabProps) {
  return (
    <>
      <section className="knowledge-panel">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Coverage</p>
          <h2 className="panel-title">{loading ? "Loading routing…" : `${alertCoverage.length} alert types tracked`}</h2>
        </div>
        <div className="knowledge-list">
          {alertCoverage.map((item) => (
            <article key={item.alertType} className={`knowledge-card ${item.hasCoverage ? "" : "knowledge-card-gap"}`}>
              <div className="knowledge-card-head">
                <div>
                  <h3 className="knowledge-card-title">{item.alertType.replace(/_/g, " ")}</h3>
                  <p className="knowledge-card-meta">
                    <span>{item.availableCount} available</span>
                    <span>·</span>
                    <span>{item.timeoutMinutes} min timeout</span>
                  </p>
                </div>
              </div>
              <div className="knowledge-gap-detail">
                <p><strong>Available:</strong> {item.availableContacts.join(", ") || "None"}</p>
                <p><strong>OOO:</strong> {item.oooContacts.join(", ") || "None"}</p>
                {!item.hasCoverage ? <p><strong>Gap:</strong> {item.gapDetails}</p> : null}
              </div>
            </article>
          ))}
        </div>
      </section>

      <section className="knowledge-panel knowledge-panel-form">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Create contact</p>
          <h2 className="panel-title">Add a contact to the alert chain</h2>
        </div>
        <div className="knowledge-form-grid">
          <label className="knowledge-field">
            <span className="knowledge-label">Alert type</span>
            <Select
              value={alertDraft.alertType}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, alertType: event.target.value }))}
            >
              {alertTypes.map((type) => (
                <option key={type} value={type}>{type}</option>
              ))}
            </Select>
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Property scope</span>
            <Select
              value={alertDraft.propertyCode}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, propertyCode: event.target.value }))}
            >
              <option value="">All properties</option>
              {alertProperties.map((property) => (
                <option key={property.propertyCode} value={property.propertyCode}>
                  {property.label}
                </option>
              ))}
            </Select>
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Contact name</span>
            <Input
              value={alertDraft.contactName}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, contactName: event.target.value }))}
            />
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Phone</span>
            <Input
              value={alertDraft.contactPhone}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, contactPhone: event.target.value }))}
            />
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Email</span>
            <Input
              value={alertDraft.contactEmail}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, contactEmail: event.target.value }))}
            />
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Escalation order</span>
            <Input
              type="number"
              min={1}
              value={alertDraft.escalationOrder}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, escalationOrder: Number(event.target.value) || 1 }))}
            />
          </label>
          <label className="knowledge-field knowledge-field-wide">
            <span className="knowledge-label">Notes</span>
            <Textarea
              rows={3}
              value={alertDraft.notes}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, notes: event.target.value }))}
            />
          </label>
          <label className="knowledge-checkbox">
            <Checkbox
              checked={alertDraft.isPrimary}
              onChange={(event) => onAlertDraftChange((current) => ({ ...current, isPrimary: event.target.checked }))}
            />
            <span>Mark as primary contact</span>
          </label>
        </div>
        <div className="knowledge-actions">
          <Button type="button" size="sm" disabled={busyId === "alert-create"} onClick={() => void onCreateAlertContact()}>
            {busyId === "alert-create" ? "Saving…" : "Save contact"}
          </Button>
        </div>
      </section>

      <section className="knowledge-panel knowledge-panel-list">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Contacts</p>
          <h2 className="panel-title">{loading ? "Loading contacts…" : `${alertContacts.length} routing contacts live`}</h2>
        </div>
        <div className="knowledge-list">
          {alertContacts.map((contact) => (
            <article key={contact.id} className="knowledge-card">
              <div className="knowledge-card-head">
                <div>
                  <h3 className="knowledge-card-title">{contact.contactName}</h3>
                  <p className="knowledge-card-meta">
                    <span>{contact.alertType}</span>
                    <span>·</span>
                    <span>{contact.propertyCode || "All properties"}</span>
                    <span>·</span>
                    <span>{contact.statusLabel}</span>
                  </p>
                </div>
                <div className="knowledge-actions">
                  <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    disabled={busyId === `alert-status-${contact.id}`}
                    onClick={() => void onToggleAvailability(contact)}
                  >
                    {contact.isAvailable ? "Mark OOO" : "Restore"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={busyId === `alert-delete-${contact.id}`}
                    onClick={() => void onDeleteAlertContact(contact.id)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
              <div className="knowledge-gap-detail">
                <p><strong>Phone:</strong> {contact.contactPhone || "—"}</p>
                <p><strong>Email:</strong> {contact.contactEmail || "—"}</p>
                <p><strong>Notes:</strong> {contact.notes || "—"}</p>
              </div>
              <div className="knowledge-actions">
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  disabled={busyId === `alert-${contact.id}`}
                  onClick={() => void onUpdateAlertContact(contact)}
                >
                  {busyId === `alert-${contact.id}` ? "Saving…" : "Re-save"}
                </Button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </>
  );
}
