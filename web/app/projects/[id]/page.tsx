"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { CompassTool, GearSix, GithubLogo, ListChecks, PaperPlaneTilt } from "@phosphor-icons/react";

import { ProjectStatusBadge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner } from "@/components/ui/error-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton, SkeletonRows } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { TaskRow } from "@/components/task-row";
import { api } from "@/lib/api";
import { agentLabel, formatTokenCount } from "@/lib/format";
import { ACTIVE_TASK_STATUSES, needsAttention } from "@/lib/status";
import type { Issue, Project, Task } from "@/lib/types";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "active", label: "Active" },
  { key: "attention", label: "Attention" },
  { key: "done", label: "Done" },
] as const;

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [issuesLoaded, setIssuesLoaded] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [discoveryBusy, setDiscoveryBusy] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [query, setQuery] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [projectResult, taskResults] = await Promise.all([api.project(id), api.tasks(id)]);
      setProject(projectResult);
      setTasks(taskResults);
      try {
        setIssues(await api.issues(id));
      } catch {
        setIssues([]);
      } finally {
        setIssuesLoaded(true);
      }
      setError("");
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    const initialRefresh = window.setTimeout(() => void refresh(), 0);
    const refreshTimer = window.setInterval(() => void refresh(), 5000);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(refreshTimer);
    };
  }, [refresh]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!prompt.trim()) return;
    setBusy(true);
    setError("");
    try {
      const task = await api.createTask(id, prompt);
      router.push(`/tasks/${task.id}`);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  }

  async function runIssue(issue: number) {
    setError("");
    try {
      const task = await api.createIssueTask(id, issue);
      router.push(`/tasks/${task.id}`);
    } catch (e) {
      setError(String(e));
    }
  }

  async function runDiscovery() {
    setError("");
    setDiscoveryBusy(true);
    try {
      const task = await api.createDiscoveryTask(id);
      router.push(`/tasks/${task.id}`);
    } catch (e) {
      setError(String(e));
      setDiscoveryBusy(false);
    }
  }

  const activeTask = useMemo(() => tasks.find((t) => ACTIVE_TASK_STATUSES.has(t.status)), [tasks]);
  const totalTokens = useMemo(() => tasks.reduce((sum, t) => sum + t.input_tokens + t.output_tokens, 0), [tasks]);

  const filteredTasks = useMemo(() => {
    let list = tasks;
    if (filter === "active") list = list.filter((t) => ACTIVE_TASK_STATUSES.has(t.status));
    else if (filter === "attention") list = list.filter((t) => needsAttention(t.status));
    else if (filter === "done") list = list.filter((t) => t.status === "DONE");
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((t) => (t.title || t.prompt).toLowerCase().includes(q));
    }
    return list;
  }, [tasks, filter, query]);

  if (!project && !error) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-16 w-1/2" />
        <Skeleton className="h-32 w-full" />
        <SkeletonRows count={4} />
      </div>
    );
  }

  if (!project) {
    return <ErrorBanner message={error} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate text-xs text-fg-muted">{project.repository_full_name || project.local_path}</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-fg">{project.name}</h1>
          <div className="mt-2.5 flex flex-wrap items-center gap-3">
            <ProjectStatusBadge status={project.status} />
            <span className="text-xs text-fg-muted">{agentLabel(project)}</span>
            <span className="rounded-sm bg-surface-raised px-1.5 py-0.5 font-mono text-[11px] text-fg-muted">{project.default_branch}</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-right text-xs text-fg-muted">
            <p className="tabular-nums">{tasks.length} tasks</p>
            <p className="tabular-nums">{formatTokenCount(totalTokens)} tokens total</p>
          </div>
          <Link href={`/projects/${id}/settings`}>
            <Button variant="secondary" aria-label="Project settings">
              <GearSix size={16} aria-hidden="true" />
              Settings
            </Button>
          </Link>
        </div>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      {activeTask ? (
        <Card className="border-status-active/30 bg-status-active/[0.04]">
          <CardBody className="flex items-center gap-3">
            <span className="h-2 w-2 shrink-0 rounded-full bg-status-active animate-live-pulse" aria-hidden="true" />
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-status-active">Active now</p>
              <Link href={`/tasks/${activeTask.id}`} className="mt-0.5 block truncate text-sm text-fg hover:text-accent">
                {activeTask.title || activeTask.prompt}
              </Link>
            </div>
            <Link href={`/tasks/${activeTask.id}`} className="shrink-0 text-xs font-medium text-accent hover:text-accent-hover">
              Watch progress →
            </Link>
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <form onSubmit={submit}>
          <CardHeader title="New autonomous task" description="Describe the desired result — AIpipe handles routing, implementation, review, CI and guarded merge." />
          <CardBody className="space-y-3">
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              className="w-full resize-y rounded-md border border-border bg-surface-sunken p-3 text-sm text-fg placeholder:text-fg-faint focus-visible:border-accent"
              placeholder="e.g. Add rate limiting to the public API and document the new limits."
            />
            <div className="flex justify-end">
              <Button type="submit" variant="primary" disabled={busy || !prompt.trim()}>
                <PaperPlaneTilt size={15} aria-hidden="true" />
                {busy ? "Queueing…" : "Run task"}
              </Button>
            </div>
          </CardBody>
        </form>
      </Card>

      {project.repository_full_name ? (
        <Card>
          <CardBody className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex items-start gap-3">
              <CompassTool size={20} weight="duotone" className="mt-0.5 shrink-0 text-fg-muted" aria-hidden="true" />
              <div>
                <p className="text-sm font-medium text-fg">Feature discovery</p>
                <p className="mt-0.5 text-xs text-fg-muted">
                  Explore the repository read-only and file ranked, deduplicated feature candidates as GitHub issues. Nothing is implemented automatically unless auto-implementation is configured.
                </p>
              </div>
            </div>
            <Button variant="secondary" onClick={runDiscovery} disabled={discoveryBusy}>
              {discoveryBusy ? "Starting…" : "Discover features"}
            </Button>
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-6 lg:grid-cols-[1.5fr_1fr]">
        <section aria-labelledby="tasks-heading">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 id="tasks-heading" className="text-sm font-semibold text-fg">
              Tasks
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <div className="flex gap-1" role="tablist" aria-label="Filter tasks">
                {FILTERS.map((f) => (
                  <button
                    key={f.key}
                    role="tab"
                    aria-selected={filter === f.key}
                    onClick={() => setFilter(f.key)}
                    className={`rounded-pill px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                      filter === f.key ? "bg-accent-solid text-accent-fg" : "border border-border bg-surface text-fg-muted hover:text-fg"
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search…"
                aria-label="Search tasks"
                className="w-32 rounded-md border border-border bg-surface px-2.5 py-1 text-xs text-fg placeholder:text-fg-faint focus-visible:border-accent"
              />
            </div>
          </div>
          {filteredTasks.length === 0 ? (
            <EmptyState icon={ListChecks} title={tasks.length === 0 ? "No tasks yet" : "No tasks match this filter"} description={tasks.length === 0 ? "Run a prompt task above or import a GitHub issue to get started." : undefined} />
          ) : (
            <Card>
              <ul className="divide-y divide-border">
                {filteredTasks.map((task) => (
                  <TaskRow key={task.id} task={task} />
                ))}
              </ul>
            </Card>
          )}
        </section>

        <section aria-labelledby="issues-heading">
          <h2 id="issues-heading" className="mb-3 text-sm font-semibold text-fg">
            Open GitHub issues
          </h2>
          <div className="max-h-[36rem] overflow-auto">
            {!issuesLoaded ? (
              <SkeletonRows count={3} />
            ) : issues.length === 0 ? (
              <EmptyState icon={GithubLogo} title="No issues available" description="Either there are no open issues, or the GitHub App isn't configured for this repository." />
            ) : (
              <div className="space-y-2">
                {issues.map((issue) => (
                  <Card key={issue.number} className="p-4">
                    <p className="font-mono text-[11px] text-fg-faint">#{issue.number}</p>
                    <p className="mt-1 text-sm font-medium text-fg">{issue.title}</p>
                    <Button variant="secondary" className="mt-3" onClick={() => runIssue(issue.number)}>
                      Run with AIpipe
                    </Button>
                  </Card>
                ))}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
