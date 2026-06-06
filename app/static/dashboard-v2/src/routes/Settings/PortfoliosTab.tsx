import { Button } from "../../components/ui/button";
import { Checkbox } from "../../components/ui/checkbox";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import type { Portfolio, PropertyOption } from "./types";

type PortfolioDraft = {
  portfolioKey: string;
  displayName: string;
  description: string;
  propertyExternalIds: string[];
};

type PortfoliosTabProps = {
  busyId: string;
  editingPortfolioId: string;
  editingPortfolioProperties: string[];
  loading: boolean;
  portfolioDraft: PortfolioDraft;
  portfolios: Portfolio[];
  propertyOptions: PropertyOption[];
  propertyLabelByExternalId: (propertyOptions: PropertyOption[], externalId: string) => string;
  onBeginPortfolioEdit: (portfolioId: string, propertyExternalIds: string[]) => void;
  onCancelPortfolioEdit: () => void;
  onCreatePortfolio: () => void | Promise<void>;
  onPortfolioDraftChange: (updater: (current: PortfolioDraft) => PortfolioDraft) => void;
  onSavePortfolioProperties: (portfolioId: string) => void | Promise<void>;
  onTogglePortfolioProperty: (
    propertyExternalId: string,
    checked: boolean,
    mode: "draft" | "edit",
  ) => void;
};

export function PortfoliosTab({
  busyId,
  editingPortfolioId,
  editingPortfolioProperties,
  loading,
  portfolioDraft,
  portfolios,
  propertyOptions,
  propertyLabelByExternalId,
  onBeginPortfolioEdit,
  onCancelPortfolioEdit,
  onCreatePortfolio,
  onPortfolioDraftChange,
  onSavePortfolioProperties,
  onTogglePortfolioProperty,
}: PortfoliosTabProps) {
  return (
    <>
      <section className="knowledge-panel knowledge-panel-form">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Create portfolio</p>
          <h2 className="panel-title">Group properties into operating areas</h2>
        </div>
        <div className="knowledge-form-grid">
          <label className="knowledge-field">
            <span className="knowledge-label">Portfolio key</span>
            <Input
              value={portfolioDraft.portfolioKey}
              onChange={(event) =>
                onPortfolioDraftChange((current) => ({ ...current, portfolioKey: event.target.value }))
              }
              placeholder="lanier"
            />
          </label>
          <label className="knowledge-field">
            <span className="knowledge-label">Display name</span>
            <Input
              value={portfolioDraft.displayName}
              onChange={(event) =>
                onPortfolioDraftChange((current) => ({ ...current, displayName: event.target.value }))
              }
              placeholder="Lanier portfolio"
            />
          </label>
          <label className="knowledge-field knowledge-field-wide">
            <span className="knowledge-label">Description</span>
            <Textarea
              rows={3}
              value={portfolioDraft.description}
              onChange={(event) =>
                onPortfolioDraftChange((current) => ({ ...current, description: event.target.value }))
              }
            />
          </label>
          <div className="knowledge-field knowledge-field-wide">
            <span className="knowledge-label">Property mapping</span>
            <div className="vendor-property-grid">
              {propertyOptions.map((property) => (
                <label key={property.externalId} className="knowledge-checkbox">
                  <Checkbox
                    checked={portfolioDraft.propertyExternalIds.includes(property.externalId)}
                    onChange={(event) =>
                      onTogglePortfolioProperty(property.externalId, event.target.checked, "draft")
                    }
                  />
                  <span>{property.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
        <div className="knowledge-actions">
          <Button type="button" size="sm" disabled={busyId === "portfolio-create"} onClick={() => void onCreatePortfolio()}>
            {busyId === "portfolio-create" ? "Saving…" : "Save portfolio"}
          </Button>
        </div>
      </section>

      <section className="knowledge-panel knowledge-panel-list">
        <div className="knowledge-panel-head">
          <p className="panel-kicker">Portfolios</p>
          <h2 className="panel-title">{loading ? "Loading portfolios…" : `${portfolios.length} portfolios live`}</h2>
        </div>
        <div className="knowledge-list">
          {portfolios.map((portfolio) => {
            const isEditing = editingPortfolioId === portfolio.id;
            const mappedProperties = isEditing ? editingPortfolioProperties : portfolio.propertyExternalIds;
            return (
              <article key={portfolio.id} className="knowledge-card">
                <div className="knowledge-card-head">
                  <div>
                    <h3 className="knowledge-card-title">{portfolio.displayName}</h3>
                    <p className="knowledge-card-meta">
                      <span>{portfolio.portfolioKey}</span>
                      <span>·</span>
                      <span>{portfolio.propertyCount} properties</span>
                    </p>
                  </div>
                  <div className="knowledge-actions">
                    {isEditing ? (
                      <>
                        <Button
                          type="button"
                          size="sm"
                          disabled={busyId === `portfolio-save-${portfolio.id}`}
                          onClick={() => void onSavePortfolioProperties(portfolio.id)}
                        >
                          {busyId === `portfolio-save-${portfolio.id}` ? "Saving…" : "Save mapping"}
                        </Button>
                        <Button type="button" variant="ghost" size="sm" onClick={onCancelPortfolioEdit}>
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={() => onBeginPortfolioEdit(portfolio.id, portfolio.propertyExternalIds)}
                      >
                        Map properties
                      </Button>
                    )}
                  </div>
                </div>
                <p className="knowledge-card-foot">{portfolio.description || "No description yet."}</p>
                <div className="settings-scope-list">
                  {mappedProperties.map((externalId) => (
                    <span key={`${portfolio.id}-${externalId}`} className="settings-chip">
                      {propertyLabelByExternalId(propertyOptions, externalId)}
                    </span>
                  ))}
                </div>
                {isEditing ? (
                  <div className="vendor-property-grid">
                    {propertyOptions.map((property) => (
                      <label key={`${portfolio.id}-${property.externalId}`} className="knowledge-checkbox">
                        <Checkbox
                          checked={editingPortfolioProperties.includes(property.externalId)}
                          onChange={(event) =>
                            onTogglePortfolioProperty(property.externalId, event.target.checked, "edit")
                          }
                        />
                        <span>{property.label}</span>
                      </label>
                    ))}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>
    </>
  );
}
