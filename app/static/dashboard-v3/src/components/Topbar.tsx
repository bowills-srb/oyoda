import { clock } from "../lib/time";

function greeting(at: Date): string {
  const h = at.getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

export function Topbar({
  operator,
  now,
  lastCheckIn,
  handled,
  watching,
  need,
  urgent,
}: {
  operator: string;
  now: Date;
  lastCheckIn: string;
  handled: number;
  watching: number;
  need: number;
  urgent: number;
}) {
  const calm = urgent === 0;
  return (
    <header className="flex shrink-0 items-center justify-between gap-4 border-b border-hairline bg-panel px-5 py-3">
      <div className="flex min-w-0 items-center gap-4">
        <div className="flex items-center gap-2">
          <span
            className="h-2 w-2 rounded-full"
            style={{ background: "var(--accent)" }}
          />
          <span className="text-[14px] font-semibold tracking-tight text-ink">
            Oyvoda
          </span>
        </div>
        <span className="hidden h-5 w-px bg-hairline sm:block" />
        <div className="min-w-0">
          <h1 className="truncate text-[14.5px] font-semibold text-ink">
            {greeting(now)}, {operator}.
          </h1>
          <p className="truncate text-[12.5px] text-muted">
            I’ve handled {handled} {handled === 1 ? "thing" : "things"} and I’m
            watching {watching}.{" "}
            {need > 0 ? (
              <span className="text-ink/80">
                {need} {need === 1 ? "needs" : "need"} a word from you.
              </span>
            ) : (
              <span className="text-ink/80">You’re all caught up.</span>
            )}
          </p>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-4">
        <span
          className="hidden items-center gap-1.5 text-[12px] font-medium sm:inline-flex"
          style={{ color: calm ? "var(--ch-voice)" : "var(--high)" }}
        >
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: calm ? "var(--ch-voice)" : "var(--high)" }}
          />
          {calm ? "All calm" : `${urgent} urgent`}
        </span>
        <span className="hidden text-[12px] text-faint md:inline">
          Last check-in · {clock(lastCheckIn)}
        </span>
        <span
          className="grid h-7 w-7 place-items-center rounded-full text-[12px] font-semibold text-bg"
          style={{ background: "var(--accent)" }}
          title={operator}
        >
          {operator.charAt(0)}
        </span>
      </div>
    </header>
  );
}
