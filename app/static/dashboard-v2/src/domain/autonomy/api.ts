import { requestJson } from "../../api/client";

import type { AutonomyPayload, PortfolioAutonomyData } from "./types";

export function fetchAutonomy() {
  return requestJson<AutonomyPayload>("/app/api/v2/autonomy");
}

export function saveAutonomy(tenant: { auto_enabled: boolean; confidence_threshold: number }) {
  return requestJson<AutonomyPayload>("/app/api/v2/autonomy", {
    method: "PUT",
    body: { tenant },
  });
}

export function fetchPortfolioAutonomy() {
  return requestJson<PortfolioAutonomyData>("/app/api/v2/portfolio-autonomy");
}
