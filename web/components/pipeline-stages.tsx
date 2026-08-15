import type { ReactNode } from "react";
import { Check, DotOutline, Prohibit, X } from "@phosphor-icons/react";
import type { ActivityFeed } from "@/lib/types";

const STAGES: { key: string; label: string }[] = [
  { key: "ROUTING", label: "Routing" },
  { key: "PREPARING", label: "Preparing" },
  { key: "DISCOVERY", label: "Discovery" },
  { key: "PLANNING", label: "Planning" },
  { key: "IMPLEMENTING", label: "Implementing" },
  { key: "VERIFYING", label: "Verifying" },
  { key: "REVIEWING", label: "Reviewing" },
  { key: "PR_OPEN", label: "PR open" },
  { key: "CI", label: "CI" },
  { key: "MERGING", label: "Merging" },
  { key: "POST_MERGE", label: "Post-merge" },
  { key: "DONE", label: "Done" },
];

type StageState = "done" | "active" | "pending" | "skipped" | "failed";

const STATE_STYLE: Record<StageState, { ring: string; text: string; icon: (props: { size: number }) => ReactNode }> = {
  done: { ring: "border-status-done/40 bg-status-done/10", text: "text-status-done", icon: (p) => <Check {...p} weight="bold" /> },
  active: { ring: "border-status-active/50 bg-status-active/10", text: "text-status-active", icon: (p) => <DotOutline {...p} weight="fill" className="animate-live-pulse" /> },
  pending: { ring: "border-border bg-transparent", text: "text-fg-faint", icon: (p) => <DotOutline {...p} /> },
  skipped: { ring: "border-border bg-transparent", text: "text-fg-faint", icon: (p) => <Prohibit {...p} /> },
  failed: { ring: "border-status-failed/50 bg-status-failed/10", text: "text-status-failed", icon: (p) => <X {...p} weight="bold" /> },
};

export function currentStageIndex(activity: ActivityFeed | null): number {
  if (!activity) return -1;
  for (let i = activity.items.length - 1; i >= 0; i--) {
    const idx = STAGES.findIndex((s) => s.key === activity.items[i].category);
    if (idx >= 0) return idx;
  }
  return -1;
}

export function PipelineStages({ activity, taskStatus }: { activity: ActivityFeed | null; taskStatus: string }) {
  const currentIndex = currentStageIndex(activity);
  const seen = new Set((activity?.items ?? []).map((i) => i.category));
  const terminalBad = ["BLOCKED", "FAILED", "CANCELLED", "NEEDS_INPUT"].includes(taskStatus);
  const isDone = taskStatus === "DONE";

  return (
    <ol className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6" aria-label="Pipeline stages">
      {STAGES.map((stage, index) => {
        let state: StageState;
        if (index < currentIndex || (isDone && index <= currentIndex)) {
          state = seen.has(stage.key) ? "done" : "skipped";
        } else if (index === currentIndex) {
          state = terminalBad ? "failed" : isDone ? "done" : "active";
        } else {
          state = "pending";
        }
        const style = STATE_STYLE[state];
        return (
          <li
            key={stage.key}
            className={`flex items-center gap-2 rounded-md border px-3 py-2.5 text-xs font-medium ${style.ring} ${style.text}`}
            aria-current={state === "active" ? "step" : undefined}
          >
            {style.icon({ size: 14 })}
            <span className="truncate">{stage.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
