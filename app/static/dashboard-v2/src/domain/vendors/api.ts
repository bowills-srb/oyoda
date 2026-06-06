import { requestJson } from "../../api/client";

export function fetchVendorCategories() {
  return requestJson<Record<string, unknown>>("/app/api/vendor-categories");
}

export function createVendorCategory(body: { slug: string; display_name: string; icon: string }) {
  return requestJson<Record<string, unknown>>("/app/api/vendor-categories", {
    method: "POST",
    body,
  });
}

export function fetchVendors(params: { category_slug?: string; workflow?: string }) {
  const search = new URLSearchParams();
  if (params.category_slug) search.set("category_slug", params.category_slug);
  if (params.workflow) search.set("workflow", params.workflow);
  const suffix = search.size ? `?${search.toString()}` : "";
  return requestJson<Record<string, unknown>>(`/app/api/vendors${suffix}`);
}

export function createVendor(body: {
  name: string;
  category_slug: string;
  phone: string;
  website: string;
  ai_script: string;
  internal_notes: string;
  priority: number;
  apply_scope: string;
  property_ids: string[];
  active: boolean;
  operational_metadata?: Record<string, unknown>;
}) {
  return requestJson<Record<string, unknown>>("/app/api/vendors", {
    method: "POST",
    body,
  });
}

export function updateVendor(
  vendorId: string,
  body: {
    name: string;
    category_slug: string;
    phone: string;
    website: string;
    ai_script: string;
    internal_notes: string;
    priority: number;
    apply_scope: string;
    property_ids: string[];
    active: boolean;
    operational_metadata?: Record<string, unknown>;
  },
) {
  return requestJson<Record<string, unknown>>(`/app/api/vendors/${encodeURIComponent(vendorId)}`, {
    method: "PATCH",
    body,
  });
}

export function deleteVendor(vendorId: string) {
  return requestJson<void>(`/app/api/vendors/${encodeURIComponent(vendorId)}`, { method: "DELETE" });
}
