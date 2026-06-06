import { useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";

import { refetchForRealtimeEvent } from "./invalidation";

const REALTIME_EVENTS = [
  "summary.updated",
  "inquiry.sent",
  "inquiry.updated",
  "kb.retry_progress",
  "autonomy.changed",
] as const;

function waitForVisibleDocument() {
  return new Promise<void>((resolve) => {
    if (typeof document === "undefined" || document.visibilityState === "visible") {
      resolve();
      return;
    }
    function handleVisible() {
      if (document.visibilityState === "visible") {
        document.removeEventListener("visibilitychange", handleVisible);
        resolve();
      }
    }
    document.addEventListener("visibilitychange", handleVisible);
  });
}

function waitForIdleConnection(timeoutMs: number) {
  return new Promise<void>((resolve) => {
    if (typeof window === "undefined") {
      resolve();
      return;
    }
    const idleCallback = (window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
    }).requestIdleCallback;
    if (typeof idleCallback === "function") {
      idleCallback(() => resolve(), { timeout: timeoutMs });
      return;
    }
    window.setTimeout(resolve, timeoutMs);
  });
}

export function RealtimeBridge() {
  const queryClient = useQueryClient();

  useEffect(() => {
    let cancelled = false;
    let stream: EventSource | null = null;

    function handleEvent(eventType: string) {
      void refetchForRealtimeEvent(queryClient, eventType);
    }

    async function connect() {
      await waitForVisibleDocument();
      await waitForIdleConnection(10_000);
      if (cancelled) return;
      stream = new EventSource("/app/api/v2/realtime", { withCredentials: true });
      REALTIME_EVENTS.forEach((eventType) => {
        stream?.addEventListener(eventType, () => handleEvent(eventType));
      });
    }

    void connect();

    return () => {
      cancelled = true;
      stream?.close();
    };
  }, [queryClient]);

  return null;
}
