import Link from "next/link";
import type { Task, TaskWithProject } from "@/lib/types";
import { formatRelativeTime } from "@/lib/format";
import { taskStatusLabel } from "@/lib/status";
import { TaskStatusBadge } from "@/components/ui/badge";

const SOURCE_LABEL: Record<string, string> = {
  prompt: "Prompt",
  github_issue: "GitHub issue",
  discovery: "Discovery",
};

export function TaskRow({ task, showProject = false }: { task: Task | TaskWithProject; showProject?: boolean }) {
  const projectName = showProject && "project_name" in task ? task.project_name : null;
  return (
    <li>
      <Link
        href={`/tasks/${task.id}`}
        className="flex items-center gap-4 px-5 py-3 transition-colors duration-150 hover:bg-surface-raised"
      >
        <TaskStatusBadge status={task.status} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm text-fg">{task.title || task.prompt}</p>
          <p className="mt-0.5 truncate text-xs text-fg-muted">
            {projectName ? `${projectName} · ` : ""}
            {SOURCE_LABEL[task.source] ?? task.source}
            {task.risk ? ` · ${task.risk} risk` : ""}
          </p>
        </div>
        <span className="hidden shrink-0 text-xs text-fg-faint sm:inline" title={taskStatusLabel(task.status)}>
          {formatRelativeTime(task.created_at)}
        </span>
      </Link>
    </li>
  );
}
