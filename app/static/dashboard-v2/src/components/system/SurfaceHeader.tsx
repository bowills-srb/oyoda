import type { ReactNode } from "react";

type SurfaceHeaderProps = {
  kicker?: string;
  title: string;
  subtitle?: string;
  /** Optional summary line rendered below subtitle — e.g. AI-activity digest. */
  summaryLine?: string;
  actions?: ReactNode;
};

export function SurfaceHeader({
  kicker = "Operator surface",
  title,
  subtitle,
  summaryLine,
  actions,
}: SurfaceHeaderProps) {
  return (
    <header className="flex justify-between items-start gap-6 pt-5 pb-3.5 px-7 sticky top-0 z-[5] bg-page border-b border-hairline max-[860px]:flex-col max-[860px]:items-stretch">
      <div className="min-w-0 grid gap-1.5">
        <p className="mb-0.5 font-mono text-[10.5px] leading-none font-medium tracking-[0.14em] uppercase text-tertiary">
          {kicker}
        </p>
        <h1 className="m-0 font-display text-[28px] leading-[1.1] tracking-[-0.01em] font-medium text-primary max-[860px]:text-[24px] max-[860px]:max-w-none">
          {title}
        </h1>
        {subtitle ? (
          <p className="m-0 mt-0.5 text-tertiary text-xs tabular-nums">{subtitle}</p>
        ) : null}
        {summaryLine ? (
          <p className="mt-0.5 text-secondary text-[12.5px] leading-[1.5] max-[640px]:text-xs">
            {summaryLine}
          </p>
        ) : null}
      </div>
      {actions ? (
        <div className="flex flex-wrap gap-2.5 items-center ml-auto">{actions}</div>
      ) : null}
    </header>
  );
}
