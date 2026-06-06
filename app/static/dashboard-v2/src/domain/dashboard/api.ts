import { requestJson } from "../../api/client";
import type { DashboardSummary } from "./types";

export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return requestJson<DashboardSummary>("/app/api/dashboard-summary");
}
