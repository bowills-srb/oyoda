export type AutonomyPayload = {
  tenant?: {
    auto_enabled?: boolean;
    confidence_threshold?: number;
    last_changed_at?: string | null;
  };
};

export type DomainBand = "Autonomous" | "Developing" | "Emerging" | "Insufficient Signal";

export type PortfolioAutonomyData = {
  portfolio_score: number;
  domain_bands: {
    inquiry: { score: number; band: DomainBand };
    guest_ops: DomainBand;
    maintenance: DomainBand;
    turnover: DomainBand;
  };
  rollup: {
    included_properties: number;
    excluded_properties: number;
    total_managed: number;
  };
  as_of: string | null;
  source: "snapshot" | "live";
};
