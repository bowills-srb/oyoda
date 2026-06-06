import { Badge } from "../../components/primitives/Badge";
import { KeyboardHint } from "../../components/primitives/KeyboardHint";
import { Button } from "../../components/ui/button";
import { SurfaceHeader } from "../../components/system/SurfaceHeader";

/**
 * Components — design-system gallery. Routed at /app/v2/components.
 *
 * Extracted from the pre-router App.tsx where it lived behind a
 * pathname.endsWith("/components") branch. Now it's a real route, which
 * makes it discoverable and linkable from internal docs.
 */
export default function ComponentsRoute() {
  return (
    <main className="grid grid-rows-[auto_auto_1fr] content-start gap-0 p-0 min-w-0 h-full overflow-y-auto [scrollbar-width:thin] [scrollbar-color:var(--border-default)_transparent]">
      <SurfaceHeader kicker="Review Route" title="Components" />
      <div className="component-stack">
        <section className="glass-panel component-panel">
          <h2 className="panel-title">Buttons</h2>
          <div className="utility-row">
            <Button>Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="danger">Danger</Button>
          </div>
        </section>
        <section className="glass-panel component-panel">
          <h2 className="panel-title">Badges</h2>
          <div className="utility-row">
            <Badge>Default</Badge>
            <Badge tone="accent">Accent</Badge>
            <Badge tone="success">Success</Badge>
            <Badge tone="warning">Warning</Badge>
            <Badge tone="danger">Danger</Badge>
          </div>
        </section>
        <section className="glass-panel component-panel">
          <h2 className="panel-title">Keyboard</h2>
          <div className="utility-row">
            <KeyboardHint>⌘K</KeyboardHint>
            <KeyboardHint>?</KeyboardHint>
            <KeyboardHint>Esc</KeyboardHint>
          </div>
        </section>
      </div>
    </main>
  );
}
