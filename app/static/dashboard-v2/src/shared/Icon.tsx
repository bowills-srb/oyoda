import React from "react";

export type IconName =
  | "inbox"
  | "spark"
  | "panel"
  | "chart"
  | "home"
  | "settings"
  | "search"
  | "chevron"
  | "sun"
  | "moon"
  | "laptop"
  | "info"
  | "arrow"
  | "user"
  | "logout"
  | "maximize"
  | "minimize";

/**
 * Icon — inline SVG icon set used across the v2 shell.
 *
 * Lives in shared/ because both the shell sidebar and individual route
 * surfaces use it. Adding a new icon: add the name to IconName and the path
 * data to `paths` below. Keep stroke widths and viewBoxes consistent so
 * icons line up at the same visual weight.
 */
export function Icon({
  name,
  size = 18,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  const paths: Record<IconName, React.ReactNode> = {
    inbox: (
      <>
        <path {...common} d="M3 7.5h4l1.5 2.5h7L17 7.5h4" />
        <path {...common} d="M4 6h16v9.5A2.5 2.5 0 0 1 17.5 18h-11A2.5 2.5 0 0 1 4 15.5Z" />
      </>
    ),
    spark: (
      <>
        <path {...common} d="m12 3 1.8 4.2L18 9l-4.2 1.8L12 15l-1.8-4.2L6 9l4.2-1.8Z" />
        <path {...common} d="m18 3 .7 1.6L20 5.3l-1.3.7L18 7.5l-.7-1.5L16 5.3l1.3-.7Z" />
      </>
    ),
    panel: (
      <>
        <rect {...common} x="3" y="4" width="18" height="16" rx="3" />
        <path {...common} d="M9 4v16" />
      </>
    ),
    chart: (
      <>
        <path {...common} d="M4 18h16" />
        <path {...common} d="M7 15V9" />
        <path {...common} d="M12 15V6" />
        <path {...common} d="M17 15v-3" />
      </>
    ),
    home: (
      <>
        <path {...common} d="M3 11 12 3l9 8" />
        <path {...common} d="M5 10v10h14V10" />
        <path {...common} d="M10 20v-6h4v6" />
      </>
    ),
    settings: (
      <>
        <path {...common} d="M12 8.5A3.5 3.5 0 1 0 12 15.5A3.5 3.5 0 1 0 12 8.5Z" />
        <path {...common} d="M19.4 15a1 1 0 0 0 .2 1.1l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1 1 0 0 0-1.1-.2 1 1 0 0 0-.6.9V20a2 2 0 0 1-4 0v-.2a1 1 0 0 0-.6-.9 1 1 0 0 0-1.1.2l-.1.1a2 2 0 0 1-2.8-2.8l.1-.1a1 1 0 0 0 .2-1.1 1 1 0 0 0-.9-.6H4a2 2 0 0 1 0-4h.2a1 1 0 0 0 .9-.6 1 1 0 0 0-.2-1.1l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1 1 0 0 0 1.1.2 1 1 0 0 0 .6-.9V4a2 2 0 0 1 4 0v.2a1 1 0 0 0 .6.9 1 1 0 0 0 1.1-.2l.1-.1a2 2 0 0 1 2.8 2.8l-.1.1a1 1 0 0 0-.2 1.1 1 1 0 0 0 .9.6H20a2 2 0 0 1 0 4h-.2a1 1 0 0 0-.4 1.9Z" />
      </>
    ),
    search: (
      <>
        <circle {...common} cx="11" cy="11" r="6" />
        <path {...common} d="m20 20-3.5-3.5" />
      </>
    ),
    chevron: <path {...common} d="m9 6 6 6-6 6" />,
    sun: (
      <>
        <circle {...common} cx="12" cy="12" r="3.5" />
        <path {...common} d="M12 2v2.2M12 19.8V22M4.9 4.9l1.5 1.5M17.6 17.6l1.5 1.5M2 12h2.2M19.8 12H22M4.9 19.1l1.5-1.5M17.6 6.4l1.5-1.5" />
      </>
    ),
    moon: <path {...common} d="M20 14.5A7.5 7.5 0 1 1 9.5 4 6.2 6.2 0 1 0 20 14.5Z" />,
    laptop: (
      <>
        <rect {...common} x="4" y="5" width="16" height="11" rx="2" />
        <path {...common} d="M2.5 19h19" />
      </>
    ),
    info: (
      <>
        <circle {...common} cx="12" cy="12" r="9" />
        <path {...common} d="M12 10v6" />
        <path {...common} d="M12 7.5h.01" />
      </>
    ),
    arrow: <path {...common} d="M5 12h14m-5-5 5 5-5 5" />,
    user: (
      <>
        <circle {...common} cx="12" cy="8" r="4" />
        <path {...common} d="M4 20c0-3.5 3.5-6 8-6s8 2.5 8 6" />
      </>
    ),
    logout: (
      <>
        <path {...common} d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" />
        <path {...common} d="m15 16 4-4-4-4" />
        <path {...common} d="M19 12H9" />
      </>
    ),
    maximize: (
      <>
        <path {...common} d="M8 3H5a2 2 0 0 0-2 2v3" />
        <path {...common} d="M16 3h3a2 2 0 0 1 2 2v3" />
        <path {...common} d="M8 21H5a2 2 0 0 1-2-2v-3" />
        <path {...common} d="M16 21h3a2 2 0 0 0 2-2v-3" />
      </>
    ),
    minimize: (
      <>
        <path {...common} d="M3 8h3a2 2 0 0 0 2-2V3" />
        <path {...common} d="M21 8h-3a2 2 0 0 1-2-2V3" />
        <path {...common} d="M3 16h3a2 2 0 0 1 2 2v3" />
        <path {...common} d="M21 16h-3a2 2 0 0 0-2 2v3" />
      </>
    ),
  };

  return (
    <svg className={className} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );
}
