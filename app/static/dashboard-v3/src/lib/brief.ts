import type { Decision, FeedUpdate } from "../types";

/*
  The morning brief. A single composed, first-person summary of the night,
  generated from the live feed and decision data — so it reads like a briefing
  from a colleague, and it updates as Lanier clears things.

  This is the "prompt composition" surface: when wired to the backend, an LLM
  would write `lines` from the same signals. The deterministic version here
  keeps the demo honest and the tone consistent.
*/

export interface Brief {
  lines: string[];
  /** The closing pointer at what needs her now — emphasized in the UI. */
  action: string;
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

export function composeBrief(
  feed: FeedUpdate[],
  decisions: Decision[],
): Brief {
  const checkins = feed.filter((f) => f.tag === "checkin").length;
  const handled = feed.filter((f) => f.tag === "handled").length;
  const bookings = feed.filter((f) => f.tag === "booking").length;
  const resolved = feed.filter((f) => f.tag === "resolved").length;
  const watching = feed.filter((f) => f.tag === "noticed").length;

  const guestActions = checkins + handled + bookings;
  const lines: string[] = [];

  lines.push(
    `It was a steady night. I handled ${guestActions} guest ${plural(
      guestActions,
      "conversation",
      "conversations",
    )} on my own and took care of ${resolved} maintenance ${plural(
      resolved,
      "issue",
      "issues",
    )} before you were up — nothing that needed waking you.`,
  );

  if (watching > 0 || bookings > 0) {
    const bits: string[] = [];
    if (bookings > 0)
      bits.push("a returning family is mid-rebooking for the holidays");
    if (watching > 0)
      bits.push(
        `I’m keeping an eye on ${watching} small ${plural(
          watching,
          "thing",
          "things",
        )} that isn’t worth acting on yet`,
      );
    lines.push(`${bits.join(", and ")}.`);
  }

  const urgent = decisions.filter((d) => d.priority === "high");
  let action: string;
  if (urgent.length > 0) {
    const top = urgent[0];
    const others = decisions.length - 1;
    action =
      `The one that can’t wait: ${top.briefLine ?? top.property}. ` +
      `That needs your call.` +
      (others > 0
        ? ` ${others} other ${plural(others, "thing", "things")} can wait until you have a minute.`
        : "");
  } else if (decisions.length > 0) {
    action = `Nothing urgent this morning — ${decisions.length} ${plural(
      decisions.length,
      "thing needs",
      "things need",
    )} a quick word from you when you can.`;
  } else {
    action =
      "You’re fully caught up. I’ll keep everything running and only surface what truly needs you.";
  }

  return { lines, action };
}
