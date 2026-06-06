export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
};

export class ApiError extends Error {
  status?: number;
  data?: unknown;
}

// /app/auth/refresh rotates the refresh token, so concurrent 401s must share
// one refresh call. Otherwise later refreshes can present a just-revoked token.
let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        const res = await fetch("/app/auth/refresh", {
          method: "POST",
          credentials: "include",
        });
        return res.ok;
      } catch {
        return false;
      } finally {
        // Clear after settle so the next 401 (post a later expiry) starts a
        // fresh rotation rather than reusing this resolved promise.
        refreshPromise = null;
      }
    })();
  }
  return refreshPromise;
}

export async function requestJson<T>(
  path: string,
  { method = "GET", body, headers = {} }: RequestOptions = {},
  _retried = false,
): Promise<T> {
  const response = await fetch(path, {
    method,
    credentials: "include",
    headers: {
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  // Replay once after a shared refresh. If refresh fails, surface the original
  // 401 so routes can show their sign-in affordance.
  if (
    response.status === 401 &&
    !_retried &&
    path !== "/app/auth/refresh"
  ) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      return requestJson<T>(path, { method, body, headers }, true);
    }
  }

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : await response.text();

  if (!response.ok) {
    const error = new ApiError(
      (data as { detail?: string; error?: string } | null)?.detail ||
        (data as { detail?: string; error?: string } | null)?.error ||
        response.statusText ||
        "Request failed",
    );
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data as T;
}
