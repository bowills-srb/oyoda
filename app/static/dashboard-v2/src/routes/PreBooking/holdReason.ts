import type { MessageFeedItem } from "../../domain/prebooking/types";

type DraftHoldInsight = {
  summary: string;
  detail: string;
  originalDraftPreview: string;
  reviewerFlags: string[];
  reviewerVerdict: string;
};

function extractTaggedValue(source: string, key: string) {
  const match = source.match(new RegExp(`${key}=([^|]+)`));
  return (match?.[1] || "").trim();
}

function humanizeToken(value: string) {
  return value
    .replace(/[_-]+/g, " ")
    .replace(/\bvrbo\b/gi, "Vrbo")
    .replace(/\be check\b/gi, "e-check")
    .replace(/\bkb\b/gi, "KB")
    .trim();
}

function formatGapTopic(topic: string) {
  return humanizeToken(topic);
}

function formatFlag(flag: string) {
  return humanizeToken(flag);
}

function sentenceCase(value: string) {
  if (!value) return "";
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function getDraftHoldInsight(item: MessageFeedItem): DraftHoldInsight | null {
  if (item.draftText?.trim()) return null;

  const fallbackReason = item.fallbackReason || "";
  const gapTopics = (item.blockedByGapTopics || []).filter(Boolean).map(formatGapTopic);
  const reviewerVerdict = extractTaggedValue(fallbackReason, "verdict");
  const flagsRaw = extractTaggedValue(fallbackReason, "flags");
  const rationale = extractTaggedValue(fallbackReason, "rationale");
  const originalDraftPreview = extractTaggedValue(fallbackReason, "orig_preview").replace(/^"+|"+$/g, "");
  const reviewerFlags = flagsRaw
    ? flagsRaw
        .split(",")
        .map((flag) => formatFlag(flag))
        .filter(Boolean)
    : [];

  const summaryParts: string[] = [];
  if (gapTopics.length) {
    summaryParts.push(`Waiting on ${gapTopics.join(", ")}`);
  }
  if (reviewerVerdict === "human_review" || reviewerVerdict === "block") {
    if (reviewerFlags.length) {
      summaryParts.push(`reviewer flagged ${reviewerFlags.slice(0, 2).join(", ")}`);
    } else {
      summaryParts.push("reviewer held the generated draft");
    }
  } else if (reviewerFlags.length) {
    summaryParts.push(`review flagged ${reviewerFlags.slice(0, 2).join(", ")}`);
  }

  let summary = summaryParts.length
    ? `Held: ${sentenceCase(summaryParts.join(" and "))}.`
    : "Held: no send-ready draft survived review.";

  if (item.routeOutcome === "historical_unprocessed") {
    summary = "Held: historical inquiry was backfilled without generating a draft.";
  }

  const detailParts: string[] = [];
  if (gapTopics.length) {
    detailParts.push(`Missing knowledge: ${gapTopics.join(", ")}.`);
  }
  if (reviewerVerdict === "human_review" || reviewerVerdict === "block") {
    detailParts.push("A generated draft existed, but review forced operator hold before it could be saved as send-ready.");
  }
  if (reviewerFlags.length) {
    detailParts.push(`Reviewer flags: ${reviewerFlags.join(", ")}.`);
  }
  if (rationale) {
    detailParts.push(sentenceCase(rationale.replace(/^"+|"+$/g, "")) + ".");
  }
  if (!detailParts.length && fallbackReason) {
    detailParts.push(sentenceCase(humanizeToken(fallbackReason.slice(0, 180))) + ".");
  }

  return {
    summary,
    detail: detailParts.join(" "),
    originalDraftPreview,
    reviewerFlags,
    reviewerVerdict,
  };
}
