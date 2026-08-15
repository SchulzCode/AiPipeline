"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Plus, MagnifyingGlass, FolderSimple } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { Project, TaskWithProject } from "@/lib/types";
import { agentLabel, formatRelativeTime } from "@/lib/format";
import { ACTIVE_TASK_STATUSES, needsAttention, projectTone, taskTone, TONE_META } from "@/lib/status";
import { ProjectStatusBadge, TaskStatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { ErrorBanner } from "@/components/ui/error-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton, SkeletonCardGrid } from "@/components/ui/skeleton";
import { TaskRow } from "@/components/task-row";

type SortKey = "recent" | "name" | "status";

export default function Overview() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [tasks, setTasks] = useState<TaskWithProject[] | null>(null);
  const [asOf, setAsOf] = useState(0);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "idle">("all");
  const [sortKey, setSortKey] = useState<SortKey>("recent");

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const [projectList, taskList] = await Promise.all([api.projects(), api.allTasks({ limit: 150 })]);
        if (cancelled) return;
        setProjects(projectList);
        setTasks(taskList);
        setAsOf(Date.now());
        setError("");
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }
    refresh();
    const interval = window.setInterval(refresh, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const activeTasks = useMemo(() => (tasks ?? []).filter((t) => ACTIVE_TASK_STATUSES.has(t.status)), [tasks]);
  const attentionTasks = useMemo(() => (tasks ?? []).filter((t) => needsAttention(t.status)), [tasks]);
  const doneToday = useMemo(() => {
    if (!tasks || !asOf) return 0;
    const dayAgo = asOf - 24 * 60 * 60 * 1000;
    return tasks.filter((t) => t.status === "DONE" && t.completed_at && new Date(t.completed_at).getTime() >= dayAgo).length;
  }, [tasks, asOf]);
  const queuedCount = useMemo(() => (tasks ?? []).filter((t) => t.status === "QUEUED").length, [tasks]);

  const lastActivityByProject = useMemo(() => {
    const map = new Map<string, TaskWithProject>();
    for (const task of tasks ?? []) {
      const existing = map.get(task.project_id);
      if (!existing || new Date(task.created_at) > new Date(existing.created_at)) map.set(task.project_id, task);
    }
    return map;
  }, [tasks]);

  const activeTaskByProject = useMemo(() => {
    const map = new Map<string, TaskWithProject>();
    for (const task of activeTasks) map.set(task.project_id, task);
    return map;
  }, [activeTasks]);

  const attentionProjectIds = useMemo(() => new Set(attentionTasks.map((t) => t.project_id)), [attentionTasks]);

  const filteredProjects = useMemo(() => {
    let list = projects ?? [];
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((p) => p.name.toLowerCase().includes(q) || (p.repository_full_name ?? "").toLowerCase().includes(q));
    }
    if (statusFilter !== "all") {
      list = list.filter((p) => (statusFilter === "active" ? projectTone(p.status) === "active" : projectTone(p.status) !== "active"));
    }
    const sorted = [...list];
    if (sortKey === "name") {
      sorted.sort((a, b) => a.name.localeCompare(b.name));
    } else if (sortKey === "status") {
      const rank: Record<string, number> = { active: 0, idle: 1 };
      sorted.sort((a, b) => (rank[projectTone(a.status)] ?? 2) - (rank[projectTone(b.status)] ?? 2) || a.name.localeCompare(b.name));
    } else {
      sorted.sort((a, b) => {
        const aTime = new Date(lastActivityByProject.get(a.id)?.created_at ?? a.created_at).getTime();
        const bTime = new Date(lastActivityByProject.get(b.id)?.created_at ?? b.created_at).getTime();
        return bTime - aTime;
      });
    }
    return sorted;
  }, [projects, query, statusFilter, sortKey, lastActivityByProject]);

  const loading = projects === null && !error;

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-fg">Overview</h1>
          <p className="mt-1 text-sm text-fg-muted">What&apos;s running, what needs attention, across every project.</p>
        </div>
        <Link
          href="/projects/new"
          className="inline-flex items-center gap-1.5 rounded-md bg-accent-solid px-3.5 py-2 text-sm font-medium text-accent-fg transition-colors duration-150 hover:bg-accent-solid-hover"
        >
          <Plus size={16} weight="bold" aria-hidden="true" />
          Add project
        </Link>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Active now" value={tasks ? activeTasks.length : null} tone="active" />
        <StatTile label="Needs attention" value={tasks ? attentionTasks.length : null} tone="attention" />
        <StatTile label="Queued" value={tasks ? queuedCount : null} tone="queued" />
        <StatTile label="Done, 24h" value={tasks ? doneToday : null} tone="done" />
      </div>

      {attentionTasks.length > 0 ? (
        <section aria-labelledby="attention-heading">
          <h2 id="attention-heading" className="mb-3 text-sm font-semibold text-status-attention">
            Needs attention ({attentionTasks.length})
          </h2>
          <Card>
            <ul className="divide-y divide-border">
              {attentionTasks.slice(0, 8).map((task) => (
                <TaskRow key={task.id} task={task} showProject />
              ))}
            </ul>
          </Card>
        </section>
      ) : null}

      <section aria-labelledby="happening-heading">
        <h2 id="happening-heading" className="mb-3 text-sm font-semibold text-fg">
          Happening now
        </h2>
        {loading ? (
          <Skeleton className="h-40 w-full" />
        ) : activeTasks.length === 0 ? (
          <EmptyState icon={FolderSimple} title="Nothing running right now" description="Queued and active tasks across every project will show up here as soon as work starts." />
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {activeTasks.slice(0, 10).map((task) => (
                <TaskRow key={task.id} task={task} showProject />
              ))}
            </ul>
          </Card>
        )}
      </section>

      <section aria-labelledby="projects-heading">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 id="projects-heading" className="text-sm font-semibold text-fg">
            Projects {projects ? `(${projects.length})` : ""}
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative">
              <MagnifyingGlass size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-faint" aria-hidden="true" />
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search projects…"
                aria-label="Search projects"
                className="w-48 rounded-md border border-border bg-surface py-1.5 pl-8 pr-3 text-sm text-fg placeholder:text-fg-faint focus-visible:border-accent"
              />
            </label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
              aria-label="Filter by status"
              className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-fg"
            >
              <option value="all">All statuses</option>
              <option value="active">Active</option>
              <option value="idle">Idle</option>
            </select>
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              aria-label="Sort projects"
              className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-sm text-fg"
            >
              <option value="recent">Recent activity</option>
              <option value="name">Name</option>
              <option value="status">Status</option>
            </select>
          </div>
        </div>

        {loading ? (
          <SkeletonCardGrid count={6} />
        ) : (projects ?? []).length === 0 ? (
          <EmptyState
            icon={FolderSimple}
            title="No projects yet"
            description="Connect a GitHub repository or a local checkout to let AIpipe start routing and implementing tasks."
            action={
              <Link href="/projects/new" className="text-sm font-medium text-accent hover:text-accent-hover">
                Add your first project →
              </Link>
            }
          />
        ) : filteredProjects.length === 0 ? (
          <EmptyState icon={MagnifyingGlass} title="No projects match your filters" description="Try a different search term or clear the status filter." />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {filteredProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                activeTask={activeTaskByProject.get(project.id)}
                lastActivity={lastActivityByProject.get(project.id)}
                needsAttention={attentionProjectIds.has(project.id)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function StatTile({ label, value, tone }: { label: string; value: number | null; tone: keyof typeof TONE_META }) {
  const meta = TONE_META[tone];
  return (
    <Card className="p-4">
      <p className="text-xs font-medium text-fg-muted">{label}</p>
      <div className={`mt-1.5 text-2xl font-semibold tabular-nums ${value ? meta.text : "text-fg"}`}>
        {value === null ? <Skeleton className="h-7 w-10" /> : value}
      </div>
    </Card>
  );
}

function ProjectCard({
  project,
  activeTask,
  lastActivity,
  needsAttention: attention,
}: {
  project: Project;
  activeTask?: TaskWithProject;
  lastActivity?: TaskWithProject;
  needsAttention: boolean;
}) {
  return (
    <Link
      href={`/projects/${project.id}`}
      className={`group block rounded-lg border bg-surface p-5 transition-colors duration-150 hover:border-border-strong ${
        attention ? "border-status-attention/40" : "border-border"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-fg">{project.name}</p>
          <p className="mt-0.5 truncate text-xs text-fg-muted">{project.repository_full_name || project.local_path || "—"}</p>
        </div>
        <ProjectStatusBadge status={project.status} />
      </div>
      <div className="mt-4 flex items-center justify-between text-xs text-fg-muted">
        <span>{agentLabel(project)}</span>
        <span className="rounded-sm bg-surface-raised px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">{project.default_branch}</span>
      </div>
      {activeTask ? (
        <div className="mt-3 flex items-center gap-2 border-t border-border pt-3 text-xs">
          <TaskStatusBadge status={activeTask.status} />
          <span className="truncate text-fg-muted">{activeTask.title || activeTask.prompt}</span>
        </div>
      ) : lastActivity ? (
        <p className="mt-3 border-t border-border pt-3 text-xs text-fg-faint">Last activity {formatRelativeTime(lastActivity.created_at)}</p>
      ) : (
        <p className="mt-3 border-t border-border pt-3 text-xs text-fg-faint">No tasks yet</p>
      )}
    </Link>
  );
}
