export type SettingsPropertyOption = {
  propertyCode: string;
  externalId: string;
  label: string;
};

export type SettingsTeamScope = {
  scope_id?: string;
  scope_type: "tenant" | "portfolio" | "property";
  portfolio_id: string;
  property_external_id: string;
  can_view: boolean;
  can_assign: boolean;
  can_manage_vendors: boolean;
  can_manage_settings: boolean;
};

export type SettingsPortfolio = {
  id: string;
  portfolioKey: string;
  displayName: string;
  description: string;
  active: boolean;
  propertyCount: number;
  propertyExternalIds: string[];
};
