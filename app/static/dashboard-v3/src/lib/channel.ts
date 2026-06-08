import type { Channel } from "../types";

export interface ChannelMeta {
  emoji: string;
  label: string;
  /** Tailwind color token (text-/border- friendly). */
  tone: string;
}

export const CHANNEL: Record<Channel, ChannelMeta> = {
  text: { emoji: "📱", label: "Text", tone: "ch-text" },
  email: { emoji: "📧", label: "Email", tone: "ch-email" },
  voice: { emoji: "🔊", label: "Voice", tone: "ch-voice" },
};

/** Heading for a drafted communication, phrased for the channel + state. */
export function draftHeading(channel: Channel, sent: boolean): string {
  if (channel === "voice") {
    return sent ? "What I said on the call" : "What I'd say on the call";
  }
  if (channel === "email") {
    return sent ? "The email I sent" : "The email I'd send";
  }
  return sent ? "The message I sent" : "The message I'd send";
}
