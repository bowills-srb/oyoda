/**
 * AutonomyCockpit — the first thing an operator sees.
 *
 * Premise (from the operator's reality): they live in their PMS inbox
 * (Hostaway/Gmail) and will never switch to Oyvoda to answer messages. So
 * Oyvoda is not a queue they work - it's the cockpit they open occasionally
 * to answer one question: "how is my AI doing against what I'd actually send,
 * and can I trust it with more so I touch the inbox less?"
 *
 * This surface leads with the verdict, backs it with evidence, and offers one
 * action: the autonomy dial. Everything binds to data the backend already
 * returns:
 *   - portfolio-autonomy  -> score + domain bands + property rollup
 *   - autonomy (GET/PUT)  -> the dial (auto on/off, confidence threshold)
 *   - dashboard-summary.pre_booking.draft_signals -> the match evidence
 *
 * Styled only with the v2 token utilities (bg-raised, border-hairline, the
 * --success/--warning/--accent families) so it sits on the same design system
 * as the rest of v2. No hand-rolled CSS.
 */
import { useState } from "react";
import type { ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { cn } from "../../../lib/utils";
import { Button } from "../../../components/ui/button";
import { dashboardSummaryQueryOptions } from "../../../domain/dashboard/queries";
import {
  autonomyQueryOptions,
  portfolioAutonomyQueryOptions,
} from "../../../domain/autonomy/queries";
import { saveAutonomy } from "../../../domain/autonomy/api";
import { queryKeys } from "../../../lib/query/queryKeys";
import { portfolioVerdict, type VerdictTone } from "../../../domain/trainingArc/stageModel";

// -- Tone styling --------------------------------------------------------------

const VERDICT_ACCENT: Record<VerdictTone, { ring: string; text: string }> = {
  ready: {
    ring: "border-[color-mix(in_srgb,var(--success-spine)_30%,var(--border-hairline))]",
    text: "text-[var(--success-text)]",
  },
  developing: {
    ring: "border-[color-mix(in_srgb,var(--accent-500)_30%,var(--border-hairline))]",
    text: "text-accent",
  },
  early: {
    ring: "border-[color-mix(in_srgb,var(--warning-spine)_28%,var(--border-hairline))]",
    text: "text-[var(--warning-text)]",
  },
  insufficient: {
    ring: "border-hairline",
    text: "text-tertiary",
  },
};

// -- Big ring gauge (the match rate, made visceral) ----------------------------

function MatchGauge({ rate, tone }: { rate: number | null; tone: VerdictTone }) {
  const size = 132;
  const stroke = 10;
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const pct = rate ?? 0;
  const dash = circ * pct;

  const strokeColor =
    tone === "ready"
      ? "var(--success-spine)"
      : tone === "developing"
        ? "var(--accent-500)"
        : tone === "early"
          ? "var(--warning-spine)"
          : "var(--border-default)";

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90" aria-hidden>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--surface-hover)"
          strokeWidth={stroke}
        />
        {rate != null && (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={strokeColor}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={`${dash} ${circ - dash}`}
            className="transition-[stroke-dasharray] duration-700 ease-out"
          />
        )}
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        {rate != null ? (
          <>
            <span className="text-[30px] font-semibold tracking-[-0.02em] tabular-nums text-primary leading-none">
              {Math.round(rate * 100)}
              <span className="text-[15px] font-medium text-tertiary">%</span>
            </span>
            <span className="mt-1 text-[10.5px] uppercase tracking-[0.06em] text-tertiary">
              match rate
            </span>
          </>
        ) : (
          <span className="text-[12px] text-tertiary text-center px-4">No signal yet</span>
        )}
      </div>
    </div>
  );
}

// -- Autonomy dial -------------------------------------------------------------

function AutonomyDial({
  autoEnabled,
  threshold,
  onSave,
  saving,
}: {
  autoEnabled: boolean;
  threshold: number;
  onSave: (next: { auto_enabled: boolean; confidence_threshold: number }) => void;
  saving: boolean;
}) {
  const [localThreshold, setLocalThreshold] = useState(Math.round(threshold * 100));
  const dirty = localThreshold !== Math.round(threshold * 100);

  return (
    <div className="rounded-xl border border-hairline bg-raised px-5 py-4 flex flex-col gap-3.5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-[11px] font-medium text-tertiary uppercase tracking-[0.06em] mb-0.5">
            Autonomy
          </p>
          <p className="text-[13px] text-secondary">
            How much your AI handles without you in the loop.
          </p>
        </div>
        <button
          type="button"
          role="switch"
          aria-checked={autoEnabled}
          aria-label="Toggle autonomous sending"
          onClick={() => onSave({ auto_enabled: !autoEnabled, confidence_threshold: localThreshold / 100 })}
          disabled={saving}
          className={cn(
            "relative w-[40px] h-[22px] rounded-full transition-colors duration-150 shrink-0 disabled:opacity-60",
            autoEnabled ? "bg-[var(--success-spine)]" : "bg-border",
          )}
        >
          <span
            className={cn(
              "absolute top-[3px] left-[3px] w-4 h-4 rounded-full bg-white transition-transform duration-150 shadow-sm",
              autoEnabled && "translate-x-[18px]",
            )}
          />
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-baseline justify-between">
          <span className="text-[11px] uppercase tracking-[0.05em] text-tertiary">
            Send on its own above
          </span>
          <span className="text-[15px] font-semibold tabular-nums text-primary">
            {localThreshold}%
          </span>
        </div>
        <input
          type="range"
          min={50}
          max={100}
          value={localThreshold}
          onChange={(e) => setLocalThreshold(Number(e.target.value))}
          disabled={!autoEnabled || saving}
          className="w-full accent-[var(--accent-600)] disabled:opacity-50"
          aria-label="Confidence threshold for autonomous sending"
        />
        <p className="text-[11.5px] text-tertiary leading-snug">
          Drafts it's at least {localThreshold}% confident in send automatically. Everything
          below waits for you.
        </p>
      </div>

      {dirty && autoEnabled && (
        <Button
          size="sm"
          disabled={saving}
          onClick={() => onSave({ auto_enabled: autoEnabled, confidence_threshold: localThreshold / 100 })}
          className="self-start"
        >
          {saving ? "Saving…" : "Save autonomy settings"}
        </Button>
      )}
    </div>
  );
}

// -- Evidence chips ------------------------------------------------------------

function EvidenceRow({
  matched,
  total,
  domainBands,
}: {
  matched: number;
  total: number;
  domainBands: { inquiry?: { band?: string } } | null;
}) {
  const misses = Math.max(0, total - matched);
  const inquiryBand = domainBands?.inquiry?.band;
  return (
    <div className="flex flex-wrap gap-2.5">
      <EvidencePill label="Sent unchanged" value={matched} tone="success" />
      <EvidencePill label="Needed your edit" value={misses} tone={misses > 0 ? "warning" : "muted"} />
      {inquiryBand ? <EvidencePill label="Pre-booking band" value={inquiryBand} tone="accent" /> : null}
    </div>
  );
}

function EvidencePill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone: "success" | "warning" | "accent" | "muted";
}) {
  const toneCls = {
    success: "text-[var(--success-text)]",
    warning: "text-[var(--warning-text)]",
    accent: "text-accent",
    muted: "text-tertiary",
  }[tone];
  return (
    <div className="rounded-lg border border-hairline bg-raised px-3.5 py-2.5 flex flex-col gap-0.5 min-w-[110px]">
      <span className={cn("text-[18px] font-semibold tabular-nums leading-none", toneCls)}>
        {value}
      </span>
      <span className="text-[11px] text-tertiary mt-1">{label}</span>
    </div>
  );
}

// -- Focus-mode lane (the "go heads-down" gesture) -----------------------------
//
// The cockpit is the calm, occasional check-in. This is its opposite-mood
// escape hatch: when exceptions are waiting and the operator IS in the system
// and wants to rip through them Superhuman-style, this deep-links into the
// existing zen focus mode (PreBookingRoute ?zen=1), which is already wired with
// j/k navigation and Enter/e/r/b triage keys. We don't rebuild focus mode -
// we make it discoverable and preview its shortcuts so the jump is informed.

function FocusModeLane({ pendingCount }: { pendingCount: number }) {
  if (pendingCount <= 0) return null;
  return (
    <Link
      to="/app/v2/prebooking?zen=1"
      className={cn(
        "group rounded-xl border border-hairline bg-raised px-5 py-4",
        "flex items-center justify-between gap-4",
        "transition-colors duration-150 hover:border-[color-mix(in_srgb,var(--accent-500)_40%,var(--border-hairline))] hover:bg-hover",
      )}
    >
      <div className="flex items-center gap-3.5 min-w-0">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--surface-hover)] text-accent">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
          </svg>
        </span>
        <div className="min-w-0">
          <p className="text-[14px] font-semibold text-primary leading-tight">
            Rip through {pendingCount} waiting {pendingCount === 1 ? "reply" : "replies"}
          </p>
          <p className="text-[12.5px] text-tertiary leading-snug">
            Heads-down focus mode — keyboard-driven, one at a time, fast.
          </p>
        </div>
      </div>
      <div className="hidden sm:flex items-center gap-1.5 shrink-0">
        <Kbd>J</Kbd>
        <Kbd>K</Kbd>
        <span className="text-tertiary text-[11px] px-0.5">move</span>
        <Kbd>↵</Kbd>
        <span className="text-tertiary text-[11px] px-0.5">send</span>
        <span className="text-tertiary opacity-0 transition-opacity group-hover:opacity-100">→</span>
      </div>
    </Link>
  );
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="inline-flex h-[20px] min-w-[20px] items-center justify-center rounded border border-hairline bg-[var(--surface-hover)] px-1.5 font-mono text-[10.5px] font-medium text-secondary">
      {children}
    </kbd>
  );
}

// -- The cockpit ---------------------------------------------------------------

export function AutonomyCockpit() {
  const queryClient = useQueryClient();
  const { data: summary } = useQuery(dashboardSummaryQueryOptions());
  const { data: autonomy } = useQuery(autonomyQueryOptions());
  const { data: portfolio } = useQuery(portfolioAutonomyQueryOptions());

  const autoEnabled = autonomy?.tenant?.auto_enabled ?? false;
  const threshold = autonomy?.tenant?.confidence_threshold ?? 0.95;
  const draftRecord = summary?.pre_booking.draft_signals ?? null;

  const verdict = portfolioVerdict(draftRecord, autoEnabled);
  const accent = VERDICT_ACCENT[verdict.tone];

  const saveMutation = useMutation({
    mutationFn: saveAutonomy,
    onSuccess: (payload) => {
      queryClient.setQueryData(queryKeys.autonomy.current(), payload);
      void queryClient.invalidateQueries({ queryKey: queryKeys.autonomy.portfolio() });
    },
  });

  // Where the primary action points.
  const actionTo =
    verdict.actionLabel === "Review the misses"
      ? "/app/v2/prebooking?tab=sent"
      : verdict.actionLabel === "See what to teach it"
        ? "/app/v2/knowledge?tab=gaps"
        : null;

  const pendingCount = summary?.pre_booking.pending ?? 0;

  function handlePrimaryAction() {
    if (verdict.actionLabel === "Let it send on its own") {
      saveMutation.mutate({ auto_enabled: true, confidence_threshold: threshold });
    }
  }

  return (
    <section className="flex flex-col gap-4">
      {/* Verdict card */}
      <div className={cn("rounded-2xl border bg-raised px-6 py-6 flex flex-col gap-5", accent.ring)}>
        <div className="flex items-center gap-6 flex-wrap">
          <MatchGauge rate={verdict.matchRate} tone={verdict.tone} />

          <div className="flex-1 min-w-[260px] flex flex-col gap-2">
            <span className={cn("text-[11px] font-medium uppercase tracking-[0.07em]", accent.text)}>
              {autoEnabled ? "Autonomous" : "Reviewing every reply"}
            </span>
            <h2 className="text-[22px] font-semibold tracking-[-0.015em] leading-tight text-primary">
              {verdict.headline}
            </h2>
            <p className="text-[13.5px] text-secondary leading-relaxed max-w-xl">
              {verdict.detail}
            </p>

            {verdict.actionLabel ? (
              <div className="mt-1.5">
                {actionTo ? (
                  <Button asChild size="sm">
                    <Link to={actionTo}>{verdict.actionLabel}</Link>
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    onClick={handlePrimaryAction}
                    disabled={saveMutation.isPending}
                  >
                    {saveMutation.isPending ? "Turning on…" : verdict.actionLabel}
                  </Button>
                )}
              </div>
            ) : null}
          </div>
        </div>

        {verdict.total > 0 ? (
          <EvidenceRow
            matched={verdict.matched}
            total={verdict.total}
            domainBands={portfolio?.domain_bands ?? null}
          />
        ) : null}
      </div>

      {/* Focus-mode lane: only when exceptions are waiting. The deliberate
          "go heads-down and rip through them" gesture into existing zen mode. */}
      <FocusModeLane pendingCount={pendingCount} />

      {/* Dial */}
      <AutonomyDial
        autoEnabled={autoEnabled}
        threshold={threshold}
        saving={saveMutation.isPending}
        onSave={(next) => saveMutation.mutate(next)}
      />
    </section>
  );
}
