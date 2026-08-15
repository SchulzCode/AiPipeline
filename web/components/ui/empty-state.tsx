import type { ReactNode } from "react";
import type { Icon } from "@phosphor-icons/react";

export function EmptyState({
  icon: IconComponent,
  title,
  description,
  action,
}: {
  icon: Icon;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center">
      <IconComponent size={28} weight="duotone" className="text-fg-faint" aria-hidden="true" />
      <div>
        <p className="text-sm font-medium text-fg">{title}</p>
        {description ? <p className="mx-auto mt-1 max-w-sm text-xs text-fg-muted">{description}</p> : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
