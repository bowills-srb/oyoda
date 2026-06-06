import { Button } from "../ui/button";

type InlineErrorProps = {
  title: string;
  detail: string;
  retryId?: string | null;
};

export function InlineError({ title, detail, retryId = null }: InlineErrorProps) {
  return (
    <div className="empty p-8">
      <div className="empty-title">{title}</div>
      <div className="empty-sub">{detail}</div>
      {retryId ? (
        <Button className="mt-3" id={retryId} type="button" variant="secondary" size="sm">
          Retry
        </Button>
      ) : null}
    </div>
  );
}
