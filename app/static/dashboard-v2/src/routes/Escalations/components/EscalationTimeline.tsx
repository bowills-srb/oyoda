/**
 * EscalationTimeline — 5-step progress strip from workflow.timeline[].
 * Rendered inside the detail drawer above the decision bar.
 */
import { cn } from "../../../lib/utils";
import type { TimelineEntry } from "../../../domain/escalations/types";

type Props = { timeline: TimelineEntry[]; currentStage: string };

export function EscalationTimeline({ timeline, currentStage }: Props) {
  return (
    <div className="flex items-start gap-0" role="list" aria-label="Escalation progress">
      {timeline.map((step, i) => {
        const isLast = i === timeline.length - 1;
        const isCurrent = step.key === currentStage && !step.done;
        const isDone = step.done;
        return (
          <div key={step.key} className="flex-1 flex flex-col items-center" role="listitem">
            {/* connector + dot row */}
            <div className="flex items-center w-full">
              {/* left connector */}
              <div className={cn("flex-1 h-0.5", i === 0 ? "invisible" : isDone ? "bg-accent" : "bg-hairline")} />
              {/* dot */}
              <div
                className={cn(
                  "w-3 h-3 rounded-full border-2 flex-shrink-0 transition-colors",
                  isDone
                    ? "border-accent bg-accent"
                    : isCurrent
                    ? "border-accent bg-page"
                    : "border-hairline bg-page",
                )}
              />
              {/* right connector */}
              <div className={cn("flex-1 h-0.5", isLast ? "invisible" : isDone ? "bg-accent" : "bg-hairline")} />
            </div>
            {/* label */}
            <p
              className={cn(
                "mt-1 text-center text-[10px] leading-tight px-0.5",
                isDone ? "text-accent font-medium" : isCurrent ? "text-primary font-medium" : "text-tertiary",
              )}
            >
              {step.label}
            </p>
          </div>
        );
      })}
    </div>
  );
}
