import type { QueryClient } from "@tanstack/react-query";

import type { AutonomyPayload } from "../autonomy/types";
import type { SessionPayload } from "../auth/types";
import { queryKeys } from "../../lib/query/queryKeys";

import { normalizePreBookingMessageFeed } from "./normalize";
import type { BootstrapPayload, MessageFeed } from "./types";

export type BootstrapCacheSnapshot = {
  session: SessionPayload;
  autonomy: AutonomyPayload | null;
  messageFeed: MessageFeed;
  tenantId: string;
  operatorId: string;
  cachedAt: number;
};

const PREBOOKING_BOOTSTRAP_CACHE_PREFIX = "oyvoda.v2.prebooking.bootstrap";
const PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY = "oyvoda.v2.prebooking.bootstrap.lastScope";

function getBootstrapScopeKey(tenantId: string, operatorId: string) {
  return `${tenantId}:${operatorId}`;
}

function getBootstrapCacheKey(tenantId: string, operatorId: string) {
  return `${PREBOOKING_BOOTSTRAP_CACHE_PREFIX}.${getBootstrapScopeKey(tenantId, operatorId)}`;
}

function safeBootstrapString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : value == null ? fallback : String(value);
}

function deriveBootstrapProperties(inquiries: unknown[]) {
  const byId = new Map<string, { id: string; name: string; count: number }>();
  for (const raw of inquiries) {
    if (!raw || typeof raw !== "object") continue;
    const item = raw as Record<string, unknown>;
    const id = safeBootstrapString(item.property_id || item.property_external_id || item.property_code);
    if (!id) continue;
    const existing = byId.get(id);
    if (existing) {
      existing.count += 1;
      continue;
    }
    byId.set(id, {
      id,
      name: safeBootstrapString(item.property_name, id),
      count: 1,
    });
  }
  return Array.from(byId.values()).sort((a, b) => a.name.localeCompare(b.name));
}

export function getBootstrapSnapshot(payload: BootstrapPayload): BootstrapCacheSnapshot | null {
  const tenantId = payload.tenant?.id || "";
  const operatorId = payload.operator?.id || "";
  if (!tenantId || !operatorId) return null;

  const session: SessionPayload = {
    operator: {
      id: payload.operator?.id,
      name: payload.operator?.name,
      email: payload.operator?.email,
      company: payload.tenant?.name,
      tenant_id: tenantId,
    },
  };
  const properties =
    Array.isArray(payload.properties) && payload.properties.length > 0
      ? payload.properties
      : deriveBootstrapProperties(Array.isArray(payload.inquiries) ? payload.inquiries : []);
  const messageFeed = normalizePreBookingMessageFeed({
    items: payload.inquiries || [],
    properties,
    count: Array.isArray(payload.inquiries) ? payload.inquiries.length : 0,
    stage: "pre_booking",
    status: "all",
  });

  return {
    session,
    autonomy: payload.autonomy || null,
    messageFeed,
    tenantId,
    operatorId,
    cachedAt: Date.now(),
  };
}

export function applyBootstrapSnapshot(snapshot: BootstrapCacheSnapshot, queryClient: QueryClient) {
  queryClient.setQueryData(queryKeys.auth.session(), snapshot.session);
  queryClient.setQueryData(queryKeys.autonomy.current(), snapshot.autonomy);
  queryClient.setQueryData(queryKeys.prebooking.feed(), snapshot.messageFeed);
}

export function applyCachedBootstrapSnapshot(
  snapshot: BootstrapCacheSnapshot,
  session: SessionPayload,
  queryClient: QueryClient,
) {
  queryClient.setQueryData(queryKeys.auth.session(), session);
  queryClient.setQueryData(queryKeys.autonomy.current(), snapshot.autonomy);
  queryClient.setQueryData(queryKeys.prebooking.feed(), snapshot.messageFeed);
}

function getBootstrapStorage() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    try {
      return window.sessionStorage;
    } catch {
      return null;
    }
  }
}

function removeLegacySessionBootstrapSnapshot() {
  if (typeof window === "undefined") return;
  try {
    const lastScope = window.sessionStorage.getItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY);
    if (lastScope) {
      window.sessionStorage.removeItem(`${PREBOOKING_BOOTSTRAP_CACHE_PREFIX}.${lastScope}`);
    }
    window.sessionStorage.removeItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY);
  } catch {
    // Ignore storage cleanup errors
  }
}

export function loadCachedBootstrapSnapshot(session: SessionPayload): BootstrapCacheSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const tenantId = session.operator?.tenant_id || "";
    const operatorId = session.operator?.id || "";
    const expectedScope = getBootstrapScopeKey(tenantId, operatorId);
    const storage = getBootstrapStorage();
    const storedScope =
      storage?.getItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY) ??
      window.sessionStorage.getItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY);
    if (!tenantId || !operatorId || storedScope !== expectedScope) return null;
    const cacheKey = getBootstrapCacheKey(tenantId, operatorId);
    const raw = storage?.getItem(cacheKey) ?? window.sessionStorage.getItem(cacheKey);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BootstrapCacheSnapshot;
    if (!parsed?.tenantId || !parsed?.operatorId || !parsed?.messageFeed) return null;
    if (parsed.tenantId !== tenantId || parsed.operatorId !== operatorId) return null;
    if (typeof parsed.cachedAt !== "number") {
      parsed.cachedAt = 0;
    }
    if (storage && storage !== window.sessionStorage) {
      storage.setItem(cacheKey, raw);
      storage.setItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY, expectedScope);
      removeLegacySessionBootstrapSnapshot();
    }
    return parsed;
  } catch {
    return null;
  }
}

export function loadMostRecentBootstrapSnapshot(): BootstrapCacheSnapshot | null {
  if (typeof window === "undefined") return null;
  try {
    const storage = getBootstrapStorage();
    const lastScope =
      storage?.getItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY) ??
      window.sessionStorage.getItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY);
    if (!lastScope) return null;
    const raw =
      storage?.getItem(`${PREBOOKING_BOOTSTRAP_CACHE_PREFIX}.${lastScope}`) ??
      window.sessionStorage.getItem(`${PREBOOKING_BOOTSTRAP_CACHE_PREFIX}.${lastScope}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BootstrapCacheSnapshot;
    if (!parsed?.tenantId || !parsed?.operatorId || !parsed?.messageFeed) return null;
    if (typeof parsed.cachedAt !== "number") {
      parsed.cachedAt = 0;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function getBootstrapSnapshotAgeMs(snapshot: BootstrapCacheSnapshot | null | undefined) {
  if (!snapshot || typeof snapshot.cachedAt !== "number" || snapshot.cachedAt <= 0) {
    return Number.POSITIVE_INFINITY;
  }
  return Math.max(0, Date.now() - snapshot.cachedAt);
}

export function isBootstrapSnapshotFresh(
  snapshot: BootstrapCacheSnapshot | null | undefined,
  maxAgeMs: number,
) {
  return getBootstrapSnapshotAgeMs(snapshot) <= maxAgeMs;
}

export function persistBootstrapSnapshot(snapshot: BootstrapCacheSnapshot) {
  if (typeof window === "undefined") return;
  const storage = getBootstrapStorage();
  if (!storage) return;
  storage.setItem(getBootstrapCacheKey(snapshot.tenantId, snapshot.operatorId), JSON.stringify(snapshot));
  storage.setItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY, getBootstrapScopeKey(snapshot.tenantId, snapshot.operatorId));
  removeLegacySessionBootstrapSnapshot();
}

export function clearCachedBootstrapSnapshot() {
  if (typeof window === "undefined") return;
  const storage = getBootstrapStorage();
  const lastScope =
    storage?.getItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY) ??
    window.sessionStorage.getItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY);
  if (lastScope) {
    storage?.removeItem(`${PREBOOKING_BOOTSTRAP_CACHE_PREFIX}.${lastScope}`);
    try {
      window.sessionStorage.removeItem(`${PREBOOKING_BOOTSTRAP_CACHE_PREFIX}.${lastScope}`);
    } catch {
      // Ignore legacy storage cleanup errors
    }
  }
  storage?.removeItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY);
  try {
    window.sessionStorage.removeItem(PREBOOKING_BOOTSTRAP_LAST_SCOPE_KEY);
  } catch {
    // Ignore legacy storage cleanup errors
  }
}

export function hydratePreBookingCacheFromStorage(queryClient: QueryClient) {
  const snapshot = loadMostRecentBootstrapSnapshot();
  if (!snapshot) return false;
  applyBootstrapSnapshot(snapshot, queryClient);
  return true;
}
