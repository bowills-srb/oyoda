export type VendorCategory = {
  id: string;
  slug: string;
  displayName: string;
  icon: string;
  sortOrder: number;
  vendorCount: number;
  workflowGroup: string;
};

export type Vendor = {
  id: string;
  name: string;
  categorySlug: string;
  phone: string;
  website: string;
  aiScript: string;
  internalNotes: string;
  priority: number;
  applyScope: string;
  propertyIds: string[];
  active: boolean;
  referralCount: number;
  lastReferredAt: string | null;
  workflowGroup: string;
  operationalMetadata: {
    manufacturerTags: string[];
    excludedManufacturerTags: string[];
    warrantyProviderTags: string[];
    supportedIssueTags: string[];
    preferredPropertyCodes: string[];
    warrantyCapable: boolean;
    warrantyOnly: boolean;
    emergencyCapable: boolean;
    emergencyOverrideOnly: boolean;
    afterHoursAvailable: boolean;
    backupRank: number;
    responseSlaMinutes: number;
    approvalMode: string;
    costTier: string;
  };
};
