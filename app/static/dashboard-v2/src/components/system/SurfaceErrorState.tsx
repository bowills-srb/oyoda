import { InlineError } from "./InlineError";
import { Button } from "../ui/button";

type SurfaceErrorStateProps = {
  title: string;
  detail: string;
  onRetry: () => void | Promise<void>;
};

export function SurfaceErrorState({ title, detail, onRetry }: SurfaceErrorStateProps) {
  return (
    <section className="queue-empty">
      <InlineError title={title} detail={detail} />
      <Button className="mt-3" size="sm" variant="secondary" type="button" onClick={() => void onRetry()}>
        Retry
      </Button>
    </section>
  );
}
