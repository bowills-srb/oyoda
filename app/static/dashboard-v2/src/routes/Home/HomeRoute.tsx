/**
 * HomeRoute — portfolio-level control surface for autonomy.
 *
 * Data: all content from GET /app/api/dashboard-summary (single fetch).
 * Loading: card-level skeletons, route progressive render.
 * Errors: route-level only if dashboard-summary fails; individual cards
 *   degrade gracefully on missing fields.
 *
 * Layout (desktop → tablet → mobile):
 *   Row 1: PortfolioAutonomyHero (full width)
 *   Row 2: TrustDriverCard (Escalation Rate — only derivable driver)
 *   Row 3: InquiryOperationsCard + GuestOperationsCard
 *   Row 4: EscalationPressureCard + KnowledgeHealthCard
 *   Row 5: PropertyReadinessCard + InboxHealthCard
 *   Row 6: AttentionFeedCard (full width)
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { dashboardSummaryQueryOptions } from "../../domain/dashboard/queries";
import type { DashboardSummary } from "../../domain/dashboard/types";
import { Button } from "../../components/ui/button";
import { SurfaceHeader } from "../../components/system/SurfaceHeader";

import { PortfolioAutonomyHero } from "./cards/PortfolioAutonomyHero";
import { AutonomyCockpit } from "./cockpit/AutonomyCockpit";
import { TrustDriverCard } from "./cards/TrustDriverCard";
import { InquiryOperationsCard } from "./cards/InquiryOperationsCard";
import { GuestOperationsCard } from "./cards/GuestOperationsCard";
import { EscalationPressureCard } from "./cards/EscalationPressureCard";
import { KnowledgeHealthCard } from "./cards/KnowledgeHealthCard";
import { PropertyReadinessCard } from "./cards/PropertyReadinessCard";
import { InboxHealthCard } from "./cards/InboxHealthCard";
import { FilteredMessagesCard } from "./cards/FilteredMessagesCard";
import { AttentionFeedCard } from "./cards/AttentionFeedCard";
import { cn } from "../../lib/utils";

function CardSkeleton({ tall }: { tall?: boolean }) {
  return (
    <div
      className={`rounded-xl border border-hairline bg-raised px-5 py-4 animate-pulse ${tall ? "min-h-[160px]" : "min-h-[120px]"}`}
      aria-hidden
    >
      <div className="h-2.5 bg-hover rounded w-24 mb-3" />
      <div className="h-7 bg-hover rounded w-16 mb-2" />
      <div className="h-2 bg-hover rounded w-32" />
    </div>
  );
}

function HeroSkeleton() {
  return (
    <div
      className="rounded-xl border border-hairline bg-raised px-7 py-6 animate-pulse min-h-[130px]"
      aria-hidden
    >
      <div className="h-2.5 bg-hover rounded w-28 mb-3" />
      <div className="h-6 bg-hover rounded w-48 mb-4" />
      <div className="h-16 bg-hover rounded-lg" />
    </div>
  );
}

function formatAge(minutes: number | null | undefined): string {
  if (typeof minutes !== "number" || !Number.isFinite(minutes) || minutes < 0) return "unknown";
  if (minutes < 60) return `${Math.round(minutes)}m`;
  if (minutes < 60 * 24) return `${Math.floor(minutes / 60)}h`;
  return `${Math.floor(minutes / (60 * 24))}d`;
}

function getBriefing(summary: DashboardSummary) {
  const pending = Number(summary.pre_booking.pending ?? 0);
  const gaps = Number(summary.kb_gaps ?? 0);
  const openEscalations = Number(summary.escalations.open ?? 0);
  const oldest = summary.pre_booking.oldest_pending_age_minutes;

  if (openEscalations > 0) {
    return {
      tone: "danger" as const,
      eyebrow: "Top priority",
      title: `${openEscalations} escalation${openEscalations === 1 ? "" : "s"} need human attention`,
      body: "Clear the live exception queue first, then return to delegation blockers.",
      to: "/app/v2/escalations",
      action: "Open Escalations",
    };
  }

  if (pending > 0) {
    const age = formatAge(oldest);
    return {
      tone: oldest && oldest > 240 ? "warning" as const : "default" as const,
      eyebrow: "Top priority",
      title: `${pending} inquiry ${pending === 1 ? "reply is" : "replies are"} waiting`,
      body: `Oldest pending item: ${age}. Use Focus to move through the queue without extra chrome.`,
      to: "/app/v2/prebooking",
      action: "Work Focus Queue",
    };
  }

  if (gaps > 0) {
    return {
      tone: "warning" as const,
      eyebrow: "Top blocker",
      title: `${gaps} knowledge ${gaps === 1 ? "gap is" : "gaps are"} limiting automation`,
      body: "Close the missing-answer queue to help Oyvoda reply without operator review.",
      to: "/app/v2/knowledge",
      action: "Resolve Gaps",
    };
  }

  return {
    tone: "success" as const,
    eyebrow: "Today",
    title: "No urgent operator queue is leading the day",
    body: "Review property readiness and governance to keep expanding safe delegation.",
    to: "/app/v2/properties",
    action: "Review Readiness",
  };
}

function CommandBriefing({ summary }: { summary: DashboardSummary }) {
  const briefing = getBriefing(summary);
  const aiSentToday = Number(summary.pre_booking.ai_sent_today ?? 0);
  const replied30d = Number(summary.pre_booking.replied_30d ?? 0);
  const activeStays = Number(summary.sessions.active ?? 0);
  const blockers = Number(summary.kb_gaps ?? 0) + Number(summary.escalations.open ?? 0);

  const toneClasses = {
    danger: "border-[var(--danger-spine)] bg-[var(--danger-fill)]",
    warning: "border-[var(--warning-spine)] bg-[var(--warning-fill)]",
    success: "border-[var(--success-spine)] bg-[var(--success-fill)]",
    default: "border-accent bg-selected",
  }[briefing.tone];

  return (
    <section className={cn("border px-5 py-4 rounded-lg", toneClasses)} aria-label="Command briefing">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-[0.06em] text-tertiary mb-1">
            {briefing.eyebrow}
          </p>
          <h2 className="text-[20px] font-semibold tracking-[-0.015em] leading-tight text-primary">
            {briefing.title}
          </h2>
          <p className="mt-1.5 text-[13px] leading-5 text-secondary max-w-2xl">
            {briefing.body}
          </p>
        </div>
        <Button asChild size="sm">
          <Link to={briefing.to}>{briefing.action}</Link>
        </Button>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
        <BriefingMetric label="AI sent today" value={aiSentToday} />
        <BriefingMetric label="Replies in 30d" value={replied30d} />
        <BriefingMetric label="Active stays" value={activeStays} />
        <BriefingMetric label="Delegation blockers" value={blockers} />
      </div>
    </section>
  );
}

function BriefingMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md border border-hairline bg-page/70 px-3 py-2">
      <p className="text-[18px] font-semibold leading-none tabular-nums text-primary">{value}</p>
      <p className="mt-1 text-[11px] text-tertiary">{label}</p>
    </div>
  );
}

export function HomeRoute() {
  const { data, isLoading, isError, error, refetch } = useQuery(dashboardSummaryQueryOptions());

  // Route-level error only if the primary fetch fails entirely.
  if (isError) {
    return (
      <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
        <div className="flex flex-col items-center justify-center gap-4 py-20 px-8 text-center">
          <p className="text-[15px] font-medium text-primary">Unable to load Home</p>
          <p className="text-[13px] text-tertiary max-w-sm">
            {(error as Error)?.message || "Dashboard summary could not be loaded."}
          </p>
          <Button variant="secondary" size="sm" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      </main>
    );
  }

  return (
    <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
      <SurfaceHeader
        kicker="Operator surface"
        title="Home"
        subtitle="Portfolio autonomy and operational overview"
      />

      <div className="px-7 py-6 flex flex-col gap-5 max-w-[1280px]">
        {/* Cockpit: the verdict + the dial. The first thing the operator sees. */}
        <AutonomyCockpit />

        {/* Row 1: Hero */}
        {isLoading ? <HeroSkeleton /> : data && <PortfolioAutonomyHero summary={data} />}

        {isLoading ? <CardSkeleton /> : data && <CommandBriefing summary={data} />}

        {/* Row 2: Trust drivers — Escalation Rate (only derivable metric) */}
        {isLoading ? (
          <CardSkeleton />
        ) : data ? (
          <TrustDriverCard summary={data} />
        ) : null}

        {/* Row 3: Inquiry + Guest operations */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {isLoading ? (
            <>
              <CardSkeleton tall />
              <CardSkeleton tall />
            </>
          ) : data ? (
            <>
              <InquiryOperationsCard summary={data} />
              <GuestOperationsCard summary={data} />
            </>
          ) : null}
        </div>

        {/* Row 4: Escalation pressure + Knowledge health */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {isLoading ? (
            <>
              <CardSkeleton />
              <CardSkeleton />
            </>
          ) : data ? (
            <>
              <EscalationPressureCard summary={data} />
              <KnowledgeHealthCard summary={data} />
            </>
          ) : null}
        </div>

        {/* Row 5: Property readiness + Inbox health + Filtered messages */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {isLoading ? (
            <>
              <CardSkeleton />
              <CardSkeleton tall />
              <CardSkeleton />
            </>
          ) : data ? (
            <>
              <PropertyReadinessCard summary={data} />
              <InboxHealthCard summary={data} />
              <FilteredMessagesCard summary={data} />
            </>
          ) : null}
        </div>

        {/* Row 6: Attention feed (full width) */}
        {isLoading ? (
          <CardSkeleton tall />
        ) : data ? (
          <AttentionFeedCard summary={data} />
        ) : null}
      </div>
    </main>
  );
}
