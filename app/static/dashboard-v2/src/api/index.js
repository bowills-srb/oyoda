/**
 * Ported from app/static/dashboard/js/api.js
 *
 * Typed fetch wrappers for every /app/api/* endpoint.
 * Kept in JavaScript intentionally for the initial v2 port.
 */

async function request(path, { method = "GET", body, headers = {} } = {}) {
  const opts = {
    method,
    credentials: "include",
    headers: { ...headers },
  };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json().catch(() => ({})) : await res.text();
  if (!res.ok) {
    const msg = (data && data.detail) || (data && data.error) || res.statusText || "Request failed";
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

async function requestMultipart(path, formData, { method = "POST", headers = {} } = {}) {
  const res = await fetch(path, {
    method,
    credentials: "include",
    headers: { ...headers },
    body: formData,
  });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json().catch(() => ({})) : await res.text();
  if (!res.ok) {
    const msg = (data && data.detail) || (data && data.error) || res.statusText || "Request failed";
    const err = new Error(msg);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  auth: {
    session: () => request("/app/auth/session"),
    refresh: () => request("/app/auth/refresh", { method: "POST" }),
    logout: () => request("/app/auth/logout", { method: "POST" }),
    changePassword: (body) => request("/app/auth/change-password", { method: "POST", body }),
  },

  summary: () => request("/app/api/dashboard-summary"),
  market: {
    intelligence: (days = 30) => request(`/app/api/market-intelligence?days=${encodeURIComponent(days)}`),
  },
  messagingObservability: (days = 7) =>
    request(`/app/api/messaging-observability?days=${encodeURIComponent(days)}`),
  messagingEvents: (limit = 12) => request(`/app/api/messaging-events?limit=${encodeURIComponent(limit)}`),
  messagingComposerEvents: (limit = 20) =>
    request(`/app/api/messaging-events?composer_only=true&limit=${encodeURIComponent(limit)}`),
  onboarding: {
    status: () => request("/app/api/onboarding-status"),
  },

  properties: () => request("/app/api/properties"),
  propertyLinks: {
    suggest: (query, limit = 5) =>
      request(
        `/app/api/property-links/suggest?query=${encodeURIComponent(query)}&limit=${encodeURIComponent(limit)}`,
      ),
    create: (body) => request("/app/api/property-links", { method: "POST", body }),
    updateProfile: (propertyCode, body) =>
      request(`/app/api/properties/${encodeURIComponent(propertyCode)}/identity`, { method: "PATCH", body }),
    reviews: (status = "pending") =>
      request(`/app/api/property-links/reviews?status=${encodeURIComponent(status)}`),
    approveReview: (reviewId, body) =>
      request(`/app/api/property-links/reviews/${encodeURIComponent(reviewId)}/approve`, { method: "POST", body }),
    rejectReview: (reviewId) =>
      request(`/app/api/property-links/reviews/${encodeURIComponent(reviewId)}/reject`, { method: "POST" }),
  },
  propertyIdentity: {
    report: () => request("/app/api/properties/identity-report"),
  },
  propertyImports: {
    upload: (file, sourceLabel = "dashboard_upload") => {
      const form = new FormData();
      form.append("file", file);
      form.append("source_label", sourceLabel);
      return requestMultipart("/app/api/properties/import", form, { method: "POST" });
    },
    profiles: () => request("/app/api/properties/import-profiles"),
    saveProfiles: (profiles) =>
      request("/app/api/properties/import-profiles", { method: "PATCH", body: { profiles } }),
    replay: (ingestEventId) =>
      request(`/app/api/properties/ingest-events/${encodeURIComponent(ingestEventId)}/replay`, { method: "POST" }),
  },
  propertyDocuments: {
    upload: ({
      file,
      documentType,
      target = "knowledge",
      scope = "property",
      propertyCode = "",
      assetType = "",
      assetName = "",
      sourceLabel = "document_upload",
    }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("document_type", documentType);
      form.append("target", target);
      form.append("scope", scope);
      form.append("source_label", sourceLabel);
      if (propertyCode) form.append("property_code", propertyCode);
      if (assetType) form.append("asset_type", assetType);
      if (assetName) form.append("asset_name", assetName);
      return requestMultipart("/app/api/properties/documents/import", form, { method: "POST" });
    },
  },
  propertyAssets: {
    list: (propertyCode) => request(`/app/api/properties/${encodeURIComponent(propertyCode)}/assets`),
    upsert: (propertyCode, body) =>
      request(`/app/api/properties/${encodeURIComponent(propertyCode)}/assets`, { method: "POST", body }),
  },
  insights: () => request("/app/api/insights"),
  propertiesAutonomy: {
    list: () => request("/app/api/properties/autonomy"),
    update: (id, body) =>
      request(`/app/api/properties/${encodeURIComponent(id)}/autonomy`, { method: "PATCH", body }),
    bulk: (body) => request("/app/api/properties/autonomy/bulk", { method: "POST", body }),
  },
  autonomy: {
    get: () => request("/app/api/v2/autonomy"),
    put: (body) => request("/app/api/v2/autonomy", { method: "PUT", body }),
  },

  team: {
    list: () => request("/app/api/team"),
    invite: (body) => request("/app/api/team/invite", { method: "POST", body }),
    remove: (id) => request(`/app/api/team/${id}`, { method: "DELETE" }),
    updateRole: (id, role) => request(`/app/api/team/${id}/role`, { method: "PATCH", body: { role } }),
    scopes: (id) => request(`/app/api/team/${encodeURIComponent(id)}/scopes`),
    updateScopes: (id, scopes) =>
      request(`/app/api/team/${encodeURIComponent(id)}/scopes`, { method: "PUT", body: { scopes } }),
  },
  portfolios: {
    list: () => request("/app/api/portfolios"),
    create: (body) => request("/app/api/portfolios", { method: "POST", body }),
    updateProperties: (id, property_external_ids) =>
      request(`/app/api/portfolios/${encodeURIComponent(id)}/properties`, {
        method: "PUT",
        body: { property_external_ids },
      }),
  },
  gateway: {
    providers: () => request("/gateway/providers"),
    credentials: () => request("/gateway/credentials"),
    upsertCredentials: (body) => request("/gateway/credentials", { method: "POST", body }),
    testCredentials: (body) => request("/gateway/credentials/test", { method: "POST", body }),
  },

  kb: {
    list: (property_id) =>
      request("/app/api/kb" + (property_id ? `?property_id=${encodeURIComponent(property_id)}` : "")),
    create: (body) => request("/app/api/kb", { method: "POST", body }),
    update: (id, body) => request(`/app/api/kb/${encodeURIComponent(id)}`, { method: "PATCH", body }),
    delete: (id) => request(`/app/api/kb/${encodeURIComponent(id)}`, { method: "DELETE" }),
    test: (question) => request("/app/api/kb/test", { method: "POST", body: { question } }),
  },

  kbGaps: {
    list: (resolved) => request("/app/api/kb-gaps" + (resolved != null ? `?resolved=${resolved}` : "")),
    resolve: (id, body) => request(`/app/api/kb-gaps/${encodeURIComponent(id)}/resolve`, { method: "POST", body }),
    dismiss: (id) => request(`/app/api/kb-gaps/${encodeURIComponent(id)}/dismiss`, { method: "POST" }),
  },

  sessions: {
    list: (params) => {
      const qs = params
        ? "?" +
          Object.entries(params)
            .filter(([, v]) => v != null && v !== "")
            .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
            .join("&")
        : "";
      return request("/app/api/sessions" + qs);
    },
    detail: (id) => request(`/app/api/sessions/${encodeURIComponent(id)}`),
    workOrders: (id) => request(`/app/api/sessions/${encodeURIComponent(id)}/work-orders`),
    sendUpdate: (id, body) =>
      request(`/app/api/sessions/${encodeURIComponent(id)}/send-update`, { method: "POST", body }),
    actions: (id) => request(`/app/api/sessions/${encodeURIComponent(id)}/actions`),
    executeAction: (id, actionType) =>
      request(`/app/api/sessions/${encodeURIComponent(id)}/actions/${encodeURIComponent(actionType)}/execute`, {
        method: "POST",
      }),
    // Added for the Today surface. Each method wraps a JWT-authenticated,
    // tenant-scoped endpoint in operator_dashboard_api.py. Kept in the same
    // order as the backend route definitions so a future reader can scan one
    // file against the other.
    dispatchVendor: (id, body) =>
      request(`/app/api/sessions/${encodeURIComponent(id)}/dispatch-vendor`, { method: "POST", body }),
    turnoverStatus: (id, body) =>
      request(`/app/api/sessions/${encodeURIComponent(id)}/turnover-status`, { method: "POST", body }),
    events: (id) => request(`/app/api/sessions/${encodeURIComponent(id)}/events`),
    recordEvent: (id, body) =>
      request(`/app/api/sessions/${encodeURIComponent(id)}/events`, { method: "POST", body }),
    requestFeedback: (id) =>
      request(`/app/api/sessions/${encodeURIComponent(id)}/request-feedback`, { method: "POST" }),
    pmsFeed: (id) => request(`/app/api/sessions/${encodeURIComponent(id)}/pms-feed`),
    importPmsEvent: (id, body) =>
      request(`/app/api/sessions/${encodeURIComponent(id)}/events/import-pms`, { method: "POST", body }),
    handoffs: (id) => request(`/app/api/sessions/${encodeURIComponent(id)}/handoffs`),
  },

  threads: {
    // Cross-session guest history. The expanded Today row uses this to answer
    // "what else has this guest done with us" — prior inquiries, prior stays,
    // and prior escalations stitched into one timeline by guest_thread_id.
    timeline: (guestThreadId) =>
      request(`/app/api/threads/${encodeURIComponent(guestThreadId)}`),
  },

  messages: {
    list: (params) => {
      const qs = params
        ? "?" +
          Object.entries(params)
            .filter(([, v]) => v != null && v !== "" && v !== false)
            .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
            .join("&")
        : "";
      return request("/app/api/messages" + qs);
    },
  },
  bookingContext: {
    lookup: (params) => {
      const qs = params
        ? "?" +
          Object.entries(params)
            .filter(([, v]) => v != null && v !== "")
            .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
            .join("&")
        : "";
      return request("/app/api/booking-context" + qs);
    },
  },
  inquiries: {
    approve: (id) => request(`/app/api/inquiries/${encodeURIComponent(id)}/approve`, { method: "POST" }),
    edit: (id, body) => request(`/app/api/inquiries/${encodeURIComponent(id)}/edit`, { method: "POST", body }),
    reject: (id) => request(`/app/api/inquiries/${encodeURIComponent(id)}/reject`, { method: "POST" }),
    bindProperty: (id, body) =>
      request(`/app/api/inquiries/${encodeURIComponent(id)}/bind-property`, { method: "POST", body }),
    regenerate: (id) => request(`/app/api/inquiries/${encodeURIComponent(id)}/regenerate`, { method: "POST" }),
    assignmentCandidates: () => request("/app/api/inquiries/assignment-candidates"),
    assign: (id, body) => request(`/app/api/inquiries/${encodeURIComponent(id)}/assign`, { method: "POST", body }),
  },

  escalations: {
    list: (status) => request("/app/api/escalations" + (status ? `?status=${status}` : "")),
    assign: (id, assigned_to) =>
      request(`/app/api/escalations/${encodeURIComponent(id)}/assign`, { method: "POST", body: { assigned_to } }),
    coordination: (id, body) =>
      request(`/app/api/escalations/${encodeURIComponent(id)}/coordination`, { method: "POST", body }),
    resolve: (id, notes) =>
      request(`/app/api/escalations/${encodeURIComponent(id)}/resolve`, { method: "POST", body: { notes } }),
    dispatchVendor: (id, body) =>
      request(`/app/api/escalations/${encodeURIComponent(id)}/dispatch-vendor`, { method: "POST", body }),
    workOrders: (id) => request(`/app/api/escalations/${encodeURIComponent(id)}/work-orders`),
    routingPreview: (id) => request(`/app/api/escalations/${encodeURIComponent(id)}/routing-preview`),
    actions: (id) => request(`/app/api/escalations/${encodeURIComponent(id)}/actions`),
    executeAction: (id, actionType) =>
      request(`/app/api/escalations/${encodeURIComponent(id)}/actions/${encodeURIComponent(actionType)}/execute`, {
        method: "POST",
      }),
  },

  vendors: {
    list: (slugOrOpts) => {
      if (!slugOrOpts) return request("/app/api/vendors");
      if (typeof slugOrOpts === "string") {
        return request("/app/api/vendors?category_slug=" + encodeURIComponent(slugOrOpts));
      }
      const qs = Object.entries(slugOrOpts)
        .filter(([, v]) => v != null && v !== "")
        .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
        .join("&");
      return request("/app/api/vendors" + (qs ? `?${qs}` : ""));
    },
    dispatch: () => request("/app/api/vendors?workflow=dispatch"),
    create: (body) => request("/app/api/vendors", { method: "POST", body }),
    update: (id, body) => request(`/app/api/vendors/${encodeURIComponent(id)}`, { method: "PATCH", body }),
    delete: (id) => request(`/app/api/vendors/${encodeURIComponent(id)}`, { method: "DELETE" }),
    categories: () => request("/app/api/vendor-categories"),
    createCategory: (body) => request("/app/api/vendor-categories", { method: "POST", body }),
  },

  settings: {
    get: () => request("/app/api/settings"),
    patch: (body) => request("/app/api/settings", { method: "PATCH", body }),
    aiGuidance: {
      get: () => request("/app/api/settings/ai-guidance"),
      put: (body) => request("/app/api/settings/ai-guidance", { method: "PUT", body }),
    },
    alertRouting: () => request("/app/api/settings/alert-routing"),
    createAlertContact: (body) => request("/app/api/settings/alert-routing", { method: "POST", body }),
    updateAlertContact: (id, body) =>
      request(`/app/api/settings/alert-routing/${encodeURIComponent(id)}`, { method: "PATCH", body }),
    markAlertOOO: (id, body) =>
      request(`/app/api/settings/alert-routing/${encodeURIComponent(id)}/ooo`, { method: "POST", body }),
    markAlertAvailable: (id) =>
      request(`/app/api/settings/alert-routing/${encodeURIComponent(id)}/available`, { method: "POST" }),
    deleteAlertContact: (id) =>
      request(`/app/api/settings/alert-routing/${encodeURIComponent(id)}`, { method: "DELETE" }),
  },

  workOrders: {
    updateStatus: (id, body) =>
      request(`/app/api/work-orders/${encodeURIComponent(id)}/status`, { method: "POST", body }),
  },

  notifications: {
    list: () => request("/app/api/notifications"),
    markAllRead: () => request("/app/api/notifications/read-all", { method: "POST" }),
  },

  admin: {
    operators: () => request("/app/api/admin/operators"),
    scope: (operator_id) => request("/app/api/admin/scope", { method: "POST", body: { operator_id } }),
    platformStats: () => request("/app/api/admin/platform-stats"),
    llmUsage: {
      summary: (window = "24h", tenantId = "") =>
        request(
          `/app/api/admin/llm-usage/summary?window=${encodeURIComponent(window)}${
            tenantId ? `&tenant_id=${encodeURIComponent(tenantId)}` : ""
          }`,
        ),
      byService: (window = "24h", tenantId = "") =>
        request(
          `/app/api/admin/llm-usage/by-service?window=${encodeURIComponent(window)}${
            tenantId ? `&tenant_id=${encodeURIComponent(tenantId)}` : ""
          }`,
        ),
      byProvider: (window = "24h", tenantId = "") =>
        request(
          `/app/api/admin/llm-usage/by-provider?window=${encodeURIComponent(window)}${
            tenantId ? `&tenant_id=${encodeURIComponent(tenantId)}` : ""
          }`,
        ),
      byTenant: (window = "24h") =>
        request(`/app/api/admin/llm-usage/by-tenant?window=${encodeURIComponent(window)}`),
      recent: ({ limit = 50, window = "24h", serviceName = "", provider = "", success = "" } = {}) => {
        const params = new URLSearchParams({ limit: String(limit), window });
        if (serviceName) params.set("service_name", serviceName);
        if (provider) params.set("provider", provider);
        if (success !== "" && success != null) params.set("success", String(success));
        return request(`/app/api/admin/llm-usage/recent?${params.toString()}`);
      },
      burnRate: (tenantId = "") =>
        request(`/app/api/admin/llm-usage/burn-rate${tenantId ? `?tenant_id=${encodeURIComponent(tenantId)}` : ""}`),
    },
  },

  raw: {
    health: () => request("/health"),
    auditSummary: (days = 30) => request(`/api/v1/audit/summary?days=${days}`),
    market: (days = 30) => request(`/api/v1/market/intelligence?days=${days}`),
  },
};

export default api;
