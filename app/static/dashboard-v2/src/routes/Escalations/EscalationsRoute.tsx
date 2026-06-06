/**
 * EscalationsRoute — /app/v2/escalations
 *
 * Uses ListDetailSurface for split geometry. Selection is tracked in URL via
 * ?selected= so the drawer survives refresh and deep links work.
 *
 * This is the second surface to prove the ReviewDrawer slot contract —
 * specifically proving that optional regions (proposedAction, confidence) are
 * genuinely optional and absent slots render nothing.
 */
import { useMemo, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useSuspenseQuery } from "@tanstack/react-query";
import { useListKeyboardNav } from "../../shared/hooks/useListKeyboardNav";
import { ListDetailSurface } from "../../components/system/ListDetailSurface";
import { EscalationQueue } from "./components/EscalationQueue";
import { EscalationDetailPanel } from "./components/EscalationDetailPanel";
import { escalationsQueryOptions } from "../../domain/escalations/queries";

export default function EscalationsRoute() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get("selected");
  const detailRef = useRef<HTMLDivElement>(null);

  const { data } = useSuspenseQuery(escalationsQueryOptions());

  const selectedItem = selectedId
    ? data.escalations.find((e) => e.ticket_id === selectedId) ?? null
    : null;

  function handleSelect(id: string) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("selected", id);
      return next;
    });
    // Focus the detail region for keyboard users
    setTimeout(() => detailRef.current?.focus(), 50);
  }

  function handleCloseDetail() {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.delete("selected");
      return next;
    });
  }

  const escalationIds = useMemo(
    () => data.escalations.map((e) => e.ticket_id),
    [data.escalations],
  );
  useListKeyboardNav({
    itemIds: escalationIds,
    selectedId: selectedId ?? "",
    onSelect: handleSelect,
    onClose: handleCloseDetail,
  });

  return (
    <main className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <ListDetailSurface
        list={
          <EscalationQueue
            items={data.escalations}
            summary={data.summary}
            selectedId={selectedId}
            onSelect={handleSelect}
          />
        }
        detail={
          selectedItem ? (
            <EscalationDetailPanel item={selectedItem} onClose={handleCloseDetail} />
          ) : undefined
        }
        detailOpen={Boolean(selectedItem)}
        onCloseDetail={handleCloseDetail}
        detailAriaLabel="Escalation detail"
        detailRef={detailRef}
        className="flex-1"
      />
    </main>
  );
}
