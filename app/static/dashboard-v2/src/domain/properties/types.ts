export type IdentityReportProperty = {
  property_code?: string;
  external_id?: string;
  display_name?: string;
  marketing_name?: string;
  pms_property_ids?: string[];
  pms_unit_codes?: string[];
  ota_refs?: Record<string, string>;
  aliases?: string[];
  knowledge_count?: number;
  asset_count?: number;
  review_status?: Record<string, number>;
  profile_updated_at?: string | null;
};
