import React from "react";

type Tone = "default" | "success" | "warning" | "danger" | "info" | "accent";

export function Badge({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}
