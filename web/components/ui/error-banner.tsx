import { WarningCircle } from "@phosphor-icons/react";

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2.5 rounded-md border border-status-failed/30 bg-status-failed/10 px-4 py-3 text-sm text-status-failed"
    >
      <WarningCircle size={18} weight="bold" className="mt-0.5 shrink-0" aria-hidden="true" />
      <p className="min-w-0 break-words">{message}</p>
    </div>
  );
}
