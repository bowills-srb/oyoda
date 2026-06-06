import { useCallback, useEffect, useState } from "react";

import { Badge } from "../../components/primitives/Badge";
import { AnchoredPanel } from "../../components/system/AnchoredPanel";
import { Button } from "../../components/ui/button";
import { Slider } from "../../components/ui/slider";
import { Switch } from "../../components/ui/switch";
import type { MessageFeedItem } from "../../domain/prebooking/types";
import { useDismissibleLayer } from "../../shared/hooks/useDismissibleLayer";

type PreBookingAutonomyPopoverProps = {
  autoEnabled: boolean;
  formatAge: (timestamp?: string | null) => string;
  formatPercent: (value: number) => string;
  inquiries: MessageFeedItem[];
  lastChangedAt?: string | null;
  onSave: (next: { auto_enabled: boolean; confidence_threshold: number }) => Promise<void>;
  threshold: number;
  thresholdAvailable: boolean;
  wasHeldForReview: (item: MessageFeedItem) => boolean;
};

export function PreBookingAutonomyPopover({
  autoEnabled,
  formatAge,
  formatPercent,
  inquiries,
  lastChangedAt,
  onSave,
  threshold,
  thresholdAvailable,
  wasHeldForReview,
}: PreBookingAutonomyPopoverProps) {
  const [open, setOpen] = useState(false);
  const [draftAuto, setDraftAuto] = useState(autoEnabled);
  const [draftThreshold, setDraftThreshold] = useState(threshold);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const closePopover = useCallback(() => setOpen(false), []);
  const anchorRef = useDismissibleLayer<HTMLDivElement>(open, closePopover);

  useEffect(() => {
    if (open) {
      setDraftAuto(autoEnabled);
      setDraftThreshold(threshold);
      setError("");
    }
  }, [open, autoEnabled, threshold]);

  const previewBase = inquiries.filter(
    (item) =>
      item.kind === "inquiry" &&
      (item.status || "").toLowerCase() === "pending_review" &&
      item.propertyId &&
      !wasHeldForReview(item) &&
      typeof item.confidence === "number",
  );
  const previewMatches = previewBase.filter((item) => (item.confidence || 0) >= draftThreshold).length;
  const previewTotal = previewBase.length;
  const previewPct = previewTotal > 0 ? Math.round((previewMatches / previewTotal) * 100) : 0;
  const dirty = draftAuto !== autoEnabled || Math.abs(draftThreshold - threshold) > 0.0001;
  const lastChangedLabel = lastChangedAt ? `Last changed ${formatAge(lastChangedAt)} ago` : "Never changed";

  async function handleSave() {
    setSaving(true);
    setError("");
    try {
      await onSave({ auto_enabled: draftAuto, confidence_threshold: draftThreshold });
      setOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AnchoredPanel
      anchorClassName="autonomy-popover-anchor"
      anchorRef={anchorRef}
      open={open}
      panelAriaLabel="Autonomy settings"
      panelClassName="autonomy-popover"
      panelRole="dialog"
      trigger={
        <button
          type="button"
          className="autonomy-trigger"
          aria-haspopup="dialog"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <Badge tone={autoEnabled ? "accent" : "warning"}>
            {autoEnabled ? "Auto mode on" : "Review mode"}
          </Badge>
          <span className="badge badge-threshold">
            Threshold {thresholdAvailable ? formatPercent(threshold) : "—"}
          </span>
        </button>
      }
      panel={
        <>
          <div className="autonomy-popover-head">
            <h3 className="autonomy-popover-title">Autonomy</h3>
            <p className="autonomy-popover-subtitle">
              Drafts at or above your threshold can send without operator review.
            </p>
          </div>

          <div className="autonomy-toggle">
            <span className="autonomy-toggle-label">
              {draftAuto ? "Auto-send enabled" : "Review every reply"}
            </span>
            <Switch
              checked={draftAuto}
              className="autonomy-switch"
              onCheckedChange={setDraftAuto}
              disabled={saving}
              aria-label="Toggle auto mode"
            />
          </div>

          <div className="autonomy-threshold">
            <div className="autonomy-threshold-head">
              <span className="autonomy-threshold-label">Confidence threshold</span>
              <span className="autonomy-threshold-value">{Math.round(draftThreshold * 100)}%</span>
            </div>
            <Slider
              className="autonomy-slider"
              min={50}
              max={99}
              step={1}
              value={Math.round(draftThreshold * 100)}
              onChange={(event) => setDraftThreshold(Number(event.target.value) / 100)}
              disabled={saving}
              aria-label="Confidence threshold percent"
            />
          </div>

          <div className="autonomy-preview">
            {previewTotal > 0 ? (
              <>
                At <strong>{Math.round(draftThreshold * 100)}%</strong>, <strong>{previewMatches}</strong> of the{" "}
                {previewTotal} draft-ready inquiries in view ({previewPct}%) would{" "}
                {draftAuto ? "auto-send" : "qualify for auto-send"}.
              </>
            ) : (
              <>No actionable drafts in view to preview against.</>
            )}
          </div>

          {error ? <p className="autonomy-error">{error}</p> : null}

          <div className="autonomy-actions">
            <span className="autonomy-actions-meta">{lastChangedLabel}</span>
            <div className="autonomy-actions-buttons">
              <Button type="button" variant="ghost" size="sm" onClick={closePopover} disabled={saving}>
                Cancel
              </Button>
              <Button type="button" size="sm" onClick={handleSave} disabled={!dirty || saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        </>
      }
    />
  );
}
