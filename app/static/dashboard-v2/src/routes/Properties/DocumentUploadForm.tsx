import { useEffect, useState } from "react";

import api from "../../api/index.js";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select } from "../../components/ui/select";

import type {
  DocumentType,
  DocumentUploadPreset,
  DocumentUploadState,
  PropertyDocumentUploadResult,
  PropertyRow,
} from "./types";

/**
 * DocumentUploadForm — property-scoped document upload preserving v1's
 * classification matrix. See docs/PROPERTIES_V2_CONTRACT.md (Contract 2).
 */

const DOCUMENT_TYPE_OPTIONS: { value: DocumentType; label: string }[] = [
  { value: "house_manual",       label: "House manual / guidebook" },
  { value: "amenities",          label: "Amenities sheet" },
  { value: "guest_qa",           label: "Guest Q&A history" },
  { value: "rental_agreement",   label: "Rental agreement" },
  { value: "equipment_warranty", label: "Equipment warranty" },
  { value: "appliance_manual",   label: "Appliance manual" },
  { value: "portfolio_policy",   label: "Portfolio policy" },
  { value: "misc",               label: "Misc document" },
];

const ASSET_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "",                label: "Infer asset type" },
  { value: "warranty",        label: "Warranty" },
  { value: "hvac",            label: "HVAC" },
  { value: "pool_equipment",  label: "Pool equipment" },
  { value: "refrigerator",    label: "Refrigerator" },
  { value: "appliance",       label: "Appliance" },
  { value: "document",        label: "General document" },
];

function availableTargets(scope: "property" | "portfolio"): readonly ("knowledge" | "asset" | "both")[] {
  if (scope === "portfolio") return ["knowledge"] as const;
  return ["knowledge", "asset", "both"] as const;
}

function availableScopes(target: "knowledge" | "asset" | "both"): readonly ("property" | "portfolio")[] {
  if (target === "asset" || target === "both") return ["property"] as const;
  return ["property", "portfolio"] as const;
}

const INITIAL_STATE: DocumentUploadState = {
  file: null,
  documentType: "house_manual",
  target: "knowledge",
  scope: "property",
  assetType: "",
  assetName: "",
  status: "idle",
  errorMessage: "",
  lastUploadFilename: "",
};

const FIELD_CLS = "flex flex-col gap-1";
const FIELD_LABEL_CLS =
  "text-[10.5px] uppercase tracking-[0.06em] text-tertiary";
const ROW_CLS = "grid grid-cols-[repeat(auto-fit,minmax(180px,1fr))] gap-2.5";

export function DocumentUploadForm({
  property,
  preset,
  onUploadSuccess,
}: {
  property: PropertyRow;
  preset?: DocumentUploadPreset | null;
  onUploadSuccess: (result: PropertyDocumentUploadResult) => void | Promise<void>;
}) {
  const [state, setState] = useState<DocumentUploadState>(INITIAL_STATE);

  useEffect(() => {
    if (!preset) return;
    setState(() => ({
      ...INITIAL_STATE,
      documentType: preset.documentType,
      target: preset.target,
      scope: preset.scope,
      status: "idle",
      errorMessage: "",
      lastUploadFilename: "",
      assetType: "",
      assetName: "",
      file: null,
    }));
  }, [preset?.contextKey]);

  useEffect(() => {
    const validTargets = availableTargets(state.scope);
    if (!validTargets.includes(state.target)) {
      setState((prev) => ({ ...prev, target: "knowledge" }));
    }
  }, [state.scope, state.target]);

  useEffect(() => {
    const validScopes = availableScopes(state.target);
    if (!validScopes.includes(state.scope)) {
      setState((prev) => ({ ...prev, scope: "property" }));
    }
  }, [state.target, state.scope]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!state.file) {
      setState((prev) => ({ ...prev, status: "error", errorMessage: "Choose a file to upload first." }));
      return;
    }
    setState((prev) => ({ ...prev, status: "uploading", errorMessage: "" }));
    try {
      const payload = await api.propertyDocuments.upload({
        file: state.file,
        documentType: state.documentType,
        target: state.target,
        scope: state.scope,
        propertyCode: state.scope === "portfolio" ? "" : property.propertyCode,
        assetType: state.assetType,
        assetName: state.assetName,
        sourceLabel: preset?.sourceLabel || "dashboard_v2_document_upload",
      });
      const filename: string = payload?.filename || state.file.name;
      setState((prev) => ({
        ...INITIAL_STATE,
        status: "success",
        lastUploadFilename: filename,
        documentType: prev.documentType,
        target: prev.target,
        scope: prev.scope,
      }));
      await onUploadSuccess(payload as PropertyDocumentUploadResult);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Upload failed.";
      setState((prev) => ({ ...prev, status: "error", errorMessage: message }));
    }
  }

  const validTargets = availableTargets(state.scope);
  const validScopes = availableScopes(state.target);
  const isAssetRelated = state.target === "asset" || state.target === "both";

  return (
    <form className="flex flex-col gap-2.5" onSubmit={handleSubmit}>
      {preset?.helperText ? (
        <p className="m-0 text-[11.5px] text-secondary">{preset.helperText}</p>
      ) : null}
      <div className={ROW_CLS}>
        <label className={FIELD_CLS}>
          <span className={FIELD_LABEL_CLS}>Document type</span>
          <Select
            value={state.documentType}
            onChange={(event) =>
              setState((prev) => ({ ...prev, documentType: event.target.value as DocumentType }))
            }
            disabled={state.status === "uploading"}
          >
            {DOCUMENT_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </label>
        <label className={FIELD_CLS}>
          <span className={FIELD_LABEL_CLS}>Target</span>
          <Select
            value={state.target}
            onChange={(event) =>
              setState((prev) => ({
                ...prev,
                target: event.target.value as DocumentUploadState["target"],
              }))
            }
            disabled={state.status === "uploading"}
          >
            {validTargets.includes("knowledge") ? (
              <option value="knowledge">Knowledge</option>
            ) : null}
            {validTargets.includes("asset") ? <option value="asset">Asset only</option> : null}
            {validTargets.includes("both") ? <option value="both">Knowledge + asset</option> : null}
          </Select>
        </label>
        <label className={FIELD_CLS}>
          <span className={FIELD_LABEL_CLS}>Scope</span>
          <Select
            value={state.scope}
            onChange={(event) =>
              setState((prev) => ({
                ...prev,
                scope: event.target.value as DocumentUploadState["scope"],
              }))
            }
            disabled={state.status === "uploading"}
          >
            {validScopes.includes("property") ? (
              <option value="property">This property</option>
            ) : null}
            {validScopes.includes("portfolio") ? (
              <option value="portfolio">Portfolio-wide</option>
            ) : null}
          </Select>
        </label>
      </div>

      {isAssetRelated ? (
        <div className={ROW_CLS}>
          <label className={FIELD_CLS}>
            <span className={FIELD_LABEL_CLS}>Asset type (optional)</span>
            <Select
              value={state.assetType}
              onChange={(event) => setState((prev) => ({ ...prev, assetType: event.target.value }))}
              disabled={state.status === "uploading"}
            >
              {ASSET_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </label>
          <label className={FIELD_CLS}>
            <span className={FIELD_LABEL_CLS}>Asset name (optional)</span>
            <Input
              type="text"
              value={state.assetName}
              onChange={(event) => setState((prev) => ({ ...prev, assetName: event.target.value }))}
              placeholder="e.g. Main HVAC, kitchen fridge"
              disabled={state.status === "uploading"}
            />
          </label>
        </div>
      ) : null}

      <div className={`${ROW_CLS} items-end`}>
        <label className={`${FIELD_CLS} col-[1/-2]`}>
          <span className={FIELD_LABEL_CLS}>File</span>
          <input
            type="file"
            className="text-xs text-secondary file:mr-2 file:py-1 file:px-2 file:rounded file:border file:border-border file:bg-raised file:text-primary file:text-xs file:cursor-pointer"
            accept=".pdf,.doc,.docx,.txt,.csv,.tsv,.xlsx,.xls,.json,.png,.jpg,.jpeg,.tiff"
            onChange={(event) => {
              const file = event.target.files?.[0] || null;
              setState((prev) => ({ ...prev, file, status: "idle", errorMessage: "" }));
            }}
            disabled={state.status === "uploading"}
          />
        </label>
        <Button
          type="submit"
          size="sm"
          disabled={state.status === "uploading" || !state.file}
        >
          {state.status === "uploading" ? "Uploading…" : "Upload"}
        </Button>
      </div>

      <p className="text-[11px] text-tertiary m-0 italic">
        {state.target === "asset" || state.target === "both"
          ? "Asset uploads must be tied to a specific property; portfolio scope is unavailable."
          : state.scope === "portfolio"
          ? "Portfolio uploads route to tenant-wide knowledge only; asset routing is unavailable."
          : "Asset type and name are inferred from the document if left blank."}
      </p>

      {state.status === "error" ? (
        <p className="text-xs m-0 px-2.5 py-2 rounded-md text-[var(--danger-text)] bg-[var(--danger-fill)]">
          {state.errorMessage}
        </p>
      ) : null}
      {state.status === "success" ? (
        <p className="text-xs m-0 px-2.5 py-2 rounded-md text-[var(--success-text)] bg-[var(--success-fill)]">
          Uploaded <strong>{state.lastUploadFilename}</strong>. Knowledge and identity counts will refresh.
        </p>
      ) : null}
    </form>
  );
}
