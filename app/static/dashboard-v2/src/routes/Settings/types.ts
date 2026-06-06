import type { normalizeSettings } from "../../adapters/index.js";

export type PropertyOption = {
  propertyCode: string;
  externalId: string;
  label: string;
};

export type AlertContact = {
  id: string;
  contactName: string;
  contactPhone: string;
  contactEmail: string;
  alertType: string;
  propertyCode: string;
  isPrimary: boolean;
  escalationOrder: number;
  timeoutMinutes: number;
  activeHours: string;
  isAvailable: boolean;
  unavailableUntil: string | null;
  redirectToId: string | null;
  notes: string;
  statusLabel: string;
};

export type AlertCoverage = {
  alertType: string;
  hasCoverage: boolean;
  availableCount: number;
  availableContacts: string[];
  oooContacts: string[];
  timeoutMinutes: number;
  gapDetails: string;
};

export type TeamMember = {
  id: string;
  email: string;
  name: string;
  role: string;
  activated: boolean;
  invitePending: boolean;
  inviteExpires: string | null;
  lastLoginAt: string | null;
  joinedAt: string | null;
};

export type TeamScope = {
  scope_id?: string;
  scope_type: "tenant" | "portfolio" | "property";
  portfolio_id: string;
  property_external_id: string;
  can_view: boolean;
  can_assign: boolean;
  can_manage_vendors: boolean;
  can_manage_settings: boolean;
};

export type Portfolio = {
  id: string;
  portfolioKey: string;
  displayName: string;
  description: string;
  active: boolean;
  propertyCount: number;
  propertyExternalIds: string[];
};

export type SettingsDraft = ReturnType<typeof normalizeSettings>["settings"];
export type SettingsData = ReturnType<typeof normalizeSettings>;
