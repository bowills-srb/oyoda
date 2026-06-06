import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { AnchoredPanel } from "../components/system/AnchoredPanel";
import { Icon } from "../shared/Icon";
import { useDismissibleLayer } from "../shared/hooks/useDismissibleLayer";
import { KeyboardHint } from "../components/primitives/KeyboardHint";
import { sessionQueryOptions } from "../domain/auth/queries";
import { preBookingMessageFeedQueryOptions } from "../domain/prebooking/queries";
import type { MessageFeed } from "../domain/prebooking/types";
import { useTheme } from "../theme/ThemeProvider";
import { cn } from "../lib/utils";
import styles from "./Shell.module.css";

/**
 * Shell — persistent app frame: sidebar, brand, primary nav, and the route
 * outlet. Lives once at the top of the router tree; every route renders
 * inside <Outlet />.
 *
 * Reads session and message-feed counts from the global store so the
 * sidebar Pre-Booking badge stays live without each route re-fetching.
 * Pre-Booking is the only surface that knows how to populate that store
 * key today; other routes will add their own counts when wired (or the
 * shell can drop to a summary endpoint later).
 *
 * The operator menu lives here (not inside Pre-Booking) because operator
 * identity and sign-out belong to the app, not to any one route.
 *
 * Sidebar expansion: React state drives onMouseEnter/Leave + onFocus/Blur
 * (with relatedTarget containment check). Shell.module.css owns the
 * grid-template-columns transition and the 860px responsive override —
 * those two rules are structurally inexpressible in Tailwind alone and are
 * explicitly component-scoped (not global).
 */

type ThemeMode = "light" | "dark" | "system";
type SessionPayload = {
  operator?: {
    id?: string;
    name?: string;
    email?: string;
    company?: string;
    tenant_id?: string;
  };
};

const NAV_ITEMS: {
  to: string;
  label: string;
  icon: "inbox" | "panel" | "chart" | "home" | "settings" | "spark";
}[] = [
  { to: "/app/v2/home", label: "Home", icon: "home" },
  { to: "/app/v2/prebooking", label: "Inquiry Operations", icon: "inbox" },
  { to: "/app/v2/escalations", label: "Escalations", icon: "panel" },
  { to: "/app/v2/today", label: "Guest Operations", icon: "panel" },
  { to: "/app/v2/properties", label: "Property Readiness", icon: "home" },
  { to: "/app/v2/knowledge", label: "Knowledge", icon: "chart" },
  { to: "/app/v2/vendors", label: "Vendors", icon: "spark" },
  { to: "/app/v2/settings", label: "Settings", icon: "settings" },
];

function getQueueBucket(item: MessageFeed["items"][number]) {
  const status = (item.status || "pending_review").toLowerCase();
  if (["replied", "sent", "auto_sent"].includes(status)) return "sent";
  if (["closed", "rejected", "expired", "archived", "resolved_without_reply"].includes(status)) return "closed";
  if (status === "pending_review") {
    if (
      item.draftSource === "kb_gap_required" ||
      item.draftSource === "gmail_fallback_saved" ||
      item.confidenceSource === "fallback_placeholder" ||
      (item.fallbackReason && item.fallbackReason.trim())
    ) {
      return "held";
    }
  }
  return "action";
}

function OperatorMenu({
  operatorName,
  operatorEmail,
  themeMode,
  onThemeChange,
}: {
  operatorName: string;
  operatorEmail: string;
  themeMode: ThemeMode;
  onThemeChange: (mode: ThemeMode) => void;
}) {
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const closeMenu = useCallback(() => setOpen(false), []);
  const anchorRef = useDismissibleLayer<HTMLDivElement>(open, closeMenu);

  async function handleSignOut() {
    setSigningOut(true);
    try {
      await fetch("/app/auth/logout", { method: "POST", credentials: "include" });
    } catch {
      // Best-effort logout — proceed with client redirect either way.
    }
    window.location.href = "/app";
  }

  return (
    <AnchoredPanel
      anchorClassName="relative inline-flex"
      anchorRef={anchorRef}
      open={open}
      panelAriaLabel="Operator menu"
      panelClassName={cn(
        "absolute top-[calc(100%+8px)] right-0 z-30 w-[260px] p-0 overflow-hidden",
        "bg-raised border border-border rounded-lg grid gap-0",
        "shadow-[0_1px_2px_rgba(15,23,42,0.04),0_8px_24px_rgba(15,23,42,0.12)]",
        "[data-theme=dark]:bg-[var(--surface-solid)]",
        "[data-theme=dark]:shadow-[0_1px_2px_rgba(0,0,0,0.4),0_12px_32px_rgba(0,0,0,0.6)]",
      )}
      panelRole="menu"
      trigger={
        <button
          type="button"
          className={cn(
            "border-0 bg-transparent p-0 cursor-pointer rounded-md transition-[box-shadow] duration-[120ms]",
            "focus-visible:outline-2 focus-visible:outline-[var(--border-focus)] focus-visible:outline-offset-2",
            "group",
          )}
          aria-haspopup="menu"
          aria-expanded={open}
          aria-label={`Operator menu for ${operatorName || "operator"}`}
          onClick={() => setOpen((v) => !v)}
        >
          <span
            className={cn(
              "inline-flex items-center justify-center w-8 h-8 rounded-md text-secondary transition-[background,color] duration-[120ms]",
              "group-hover:bg-hover group-hover:text-primary",
              open && "bg-hover text-primary",
            )}
            aria-hidden="true"
          >
            <Icon name="user" size={18} />
          </span>
        </button>
      }
      panel={
        <>
          {/* Head */}
          <div className="flex items-center gap-2.5 px-3.5 pt-3.5 pb-3 border-b border-hairline">
            <span
              className="inline-flex items-center justify-center w-9 h-9 rounded-md bg-hover text-secondary flex-shrink-0"
              aria-hidden="true"
            >
              <Icon name="user" size={22} />
            </span>
            <div className="grid gap-px min-w-0 flex-1">
              <strong className="text-[13px] font-semibold text-primary overflow-hidden text-ellipsis whitespace-nowrap">
                {operatorName || "Operator"}
              </strong>
              <span className="text-tertiary text-[11.5px] overflow-hidden text-ellipsis whitespace-nowrap">
                {operatorEmail || "Signed in"}
              </span>
            </div>
          </div>

          {/* Theme section */}
          <div className="px-3.5 py-2.5 grid gap-2 border-b border-hairline">
            <span className="text-tertiary text-[10.5px] font-medium tracking-[0.06em] uppercase">
              Theme
            </span>
            <div className="grid grid-cols-3 gap-1" role="radiogroup" aria-label="Theme">
              {(["system", "light", "dark"] as ThemeMode[]).map((modeOption) => {
                const isActive = themeMode === modeOption;
                return (
                  <button
                    key={modeOption}
                    type="button"
                    role="radio"
                    aria-checked={isActive}
                    className={cn(
                      "inline-flex items-center justify-center gap-[5px] border rounded-md px-1 py-1.5 cursor-pointer",
                      "text-[11.5px] font-medium transition-[background,color,border-color] duration-100",
                      isActive
                        ? "bg-selected border-accent text-[var(--accent-700)] [data-theme=dark]:text-[var(--accent-500)]"
                        : "bg-transparent border-border text-secondary hover:bg-hover hover:text-primary",
                    )}
                    onClick={() => onThemeChange(modeOption)}
                  >
                    {modeOption === "light" ? (
                      <Icon name="sun" size={14} />
                    ) : modeOption === "dark" ? (
                      <Icon name="moon" size={14} />
                    ) : (
                      <Icon name="laptop" size={14} />
                    )}
                    <span>{modeOption[0].toUpperCase() + modeOption.slice(1)}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Sign out */}
          <div className="px-2 py-2.5">
            <button
              type="button"
              className={cn(
                "inline-flex items-center gap-2 w-full border-0 bg-transparent text-primary",
                "px-2.5 py-2 rounded-md text-[13px] font-medium cursor-pointer text-left",
                "hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60",
                "[&_svg]:text-tertiary hover:[&_svg]:text-primary",
              )}
              onClick={handleSignOut}
              disabled={signingOut}
              role="menuitem"
            >
              <Icon name="logout" size={14} />
              <span>{signingOut ? "Signing out…" : "Sign out"}</span>
            </button>
          </div>
        </>
      }
    />
  );
}

export function Shell() {
  const { mode, setMode } = useTheme();
  const location = useLocation();
  const [sidebarExpanded, setSidebarExpanded] = useState(false);
  const isPreBookingSurface = location.pathname.startsWith("/app/v2/prebooking");
  const { data: session } = useQuery(sessionQueryOptions());
  const { data: feed } = useQuery({
    ...preBookingMessageFeedQueryOptions(),
    enabled: isPreBookingSurface,
  });

  const operator = session?.operator;
  const workspaceLabel = (operator?.company || "").trim() || "Operator workspace";
  const actionCount = useMemo(
    () => (feed ? feed.items.filter((item) => getQueueBucket(item) === "action").length : null),
    [feed],
  );

  const isComponents = location.pathname.endsWith("/components");
  if (isComponents) {
    return <Outlet />;
  }

  // Fade classes for sidebar labels when collapsed.
  const labelFade = cn(
    "transition-opacity",
    sidebarExpanded
      ? "opacity-100 duration-[180ms] delay-100"
      : "opacity-0 duration-100 pointer-events-none",
  );

  return (
    <div className={styles.shell}>
      {/* Sticky topbar */}
      <header
        className={cn(
          "flex items-center justify-between px-5 border-b border-hairline bg-page sticky top-0 z-20",
          "max-[860px]:px-3.5 max-[860px]:py-2.5 max-[860px]:gap-3",
        )}
      >
        <div className="flex items-center gap-2.5 flex-shrink-0">
          <span className="text-[15px] font-semibold tracking-[-0.015em] text-primary leading-none">
            oyvoda
          </span>
        </div>
        <div className="flex-1" aria-hidden />
        <div className="flex items-center gap-3 max-[860px]:justify-end">
          <span className="text-xs font-medium text-tertiary whitespace-nowrap overflow-hidden text-ellipsis max-w-[200px] tracking-[-0.005em]">
            {workspaceLabel}
          </span>
          <div className="flex items-center gap-3">
            <span
              className="w-7 h-7 rounded-md bg-selected grid place-items-center font-semibold text-xs text-accent flex-shrink-0"
              aria-hidden
              title={operator?.name || "Operator"}
            >
              {(operator?.name || "O").charAt(0).toUpperCase()}
            </span>
            <div className="grid gap-px min-w-0">
              <strong className="text-[13px] font-medium text-primary overflow-hidden text-ellipsis whitespace-nowrap">
                {operator?.name || "Operator"}
              </strong>
              <span className="text-[11.5px] text-tertiary overflow-hidden text-ellipsis whitespace-nowrap">
                {operator?.email || "Signed in"}
              </span>
            </div>
            <OperatorMenu
              operatorName={operator?.name || ""}
              operatorEmail={operator?.email || ""}
              themeMode={mode as ThemeMode}
              onThemeChange={(next) => setMode(next)}
            />
          </div>
        </div>
      </header>

      {/* App frame — sidebar + outlet */}
      <div className={cn(styles.frame, sidebarExpanded && styles.frameExpanded)}>
        <aside
          className={cn(
            "grid [grid-template-rows:auto_1fr_auto] gap-6 self-stretch h-full",
            "sticky top-0 py-5 px-3 border-r border-hairline bg-page overflow-hidden z-10",
            "max-[860px]:static max-[860px]:border-r-0 max-[860px]:pr-0",
          )}
          onMouseEnter={() => setSidebarExpanded(true)}
          onMouseLeave={() => setSidebarExpanded(false)}
          onFocus={() => setSidebarExpanded(true)}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
              setSidebarExpanded(false);
            }
          }}
        >
          {/* Nav */}
          <nav className="grid gap-px" aria-label="Primary">
            {NAV_ITEMS.map((item) => {
              const showCount = item.to === "/app/v2/prebooking" && actionCount !== null;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }: { isActive: boolean }) =>
                    cn(
                      "relative flex items-center justify-between gap-2.5 px-2.5 py-[7px]",
                      "text-[13.5px] transition-colors duration-[120ms]",
                      isActive ? "text-primary" : "text-secondary hover:text-primary",
                    )
                  }
                >
                  {({ isActive }: { isActive: boolean }) => (
                    <>
                      {/* Active rail — visible even when sidebar is collapsed */}
                      {isActive && (
                        <span
                          aria-hidden
                          className="absolute left-0 top-2 bottom-2 w-0.5 rounded-r bg-accent"
                        />
                      )}
                      <span className="inline-flex items-center gap-2.5">
                        <Icon
                          name={item.icon}
                          size={16}
                          className={isActive ? "text-primary" : "text-tertiary"}
                        />
                        <span className={labelFade}>{item.label}</span>
                      </span>
                      {showCount ? (
                        <span className={cn("text-xs text-tertiary tabular-nums", labelFade)}>
                          {actionCount}
                        </span>
                      ) : (
                        <Icon
                          name="chevron"
                          size={14}
                          className={cn("text-tertiary", labelFade)}
                        />
                      )}
                    </>
                  )}
                </NavLink>
              );
            })}
          </nav>

          {/* Spacer (empty middle row) */}
          <div />

          {/* Keyboard shortcuts */}
          <div
            className={cn(
              "grid gap-1.5 px-2.5 pt-3 border-t border-hairline",
              labelFade,
            )}
          >
            <p className="m-0 text-tertiary text-[11px] leading-none font-normal tracking-[0.06em] uppercase mb-1.5">
              Keyboard
            </p>
            <div className="flex items-center gap-2.5 text-tertiary text-[12.5px]">
              <KeyboardHint>g a</KeyboardHint>
              <span className="text-secondary">Action queue</span>
            </div>
            <div className="flex items-center gap-2.5 text-tertiary text-[12.5px]">
              <KeyboardHint>g s</KeyboardHint>
              <span className="text-secondary">Sent queue</span>
            </div>
            <div className="flex items-center gap-2.5 text-tertiary text-[12.5px]">
              <KeyboardHint>?</KeyboardHint>
              <span className="text-secondary">Shortcut overlay</span>
            </div>
          </div>
        </aside>

        <div className="min-h-0 h-full">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
