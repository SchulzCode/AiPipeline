"use client";

import { useEffect, useMemo, useState } from "react";
import { ListChecks } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { TaskWithProject } from "@/lib/types";
import { ErrorBanner } from "@/components/ui/error-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { SkeletonRows } from "@/components/ui/skeleton";
import { Card } from "@/components/ui/card";
import { TaskRow } from "@/components/task-row";

const STATUS_GROUPS: { key: string; label: string; statuses: string[] }[] = [
  { key: "all", label: "All", statuses: [] },
  { key: "active", label: "Active", statuses: ["CLAIMED", "ROUTING", "PREPARING", "DISCOVERY", "DISCOVERING", "PLANNING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "PR_OPEN", "CI", "MERGING", "POST_MERGE"] },
  { key: "queued", label: "Queued", statuses: ["QUEUED"] },
  { key: "attention", label: "Attention", statuses: ["BLOCKED", "NEEDS_INPUT"] },
  { key: "failed", label: "Failed", statuses: ["FAILED"] },
  { key: "done", label: "Done", statuses: ["DONE"] },
];

const SOURCES = [
  { key: "all", label: "All sources" },
  { key: "prompt", label: "Prompt" },
  { key: "github_issue", label: "GitHub issue" },
  { key: "discovery", label: "Discovery" },
];

export default function GlobalTasksPage() {
  const [tasks, setTasks] = useState<TaskWithProject[] | null>(null);
  const [error, setError] = useState("");
  const [group, setGroup] = useState("all");
  const [source, setSource] = useState("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const list = await api.allTasks({ limit: 300 });
        if (!cancelled) {
          setTasks(list);
          setError("");
        }
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

  const activeGroup = STATUS_GROUPS.find((g) => g.key === group) ?? STATUS_GROUPS[0];

  const filtered = useMemo(() => {
    let list = tasks ?? [];
    if (activeGroup.statuses.length > 0) list = list.filter((t) => activeGroup.statuses.includes(t.status));
    if (source !== "all") list = list.filter((t) => t.source === source);
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((t) => (t.title || t.prompt).toLowerCase().includes(q) || t.project_name.toLowerCase().includes(q));
    }
    return list;
  }, [tasks, activeGroup, source, query]);

  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const g of STATUS_GROUPS) {
      map.set(g.key, g.statuses.length === 0 ? (tasks ?? []).length : (tasks ?? []).filter((t) => g.statuses.includes(t.status)).length);
    }
    return map;
  }, [tasks]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-fg">Tasks</h1>
        <p className="mt-1 text-sm text-fg-muted">Every autonomous task across every project, newest first.</p>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by status">
          {STATUS_GROUPS.map((g) => (
            <button
              key={g.key}
              role="tab"
              aria-selected={group === g.key}
              onClick={() => setGroup(g.key)}
              className={`rounded-pill px-3 py-1.5 text-xs font-medium transition-colors duration-150 ${
                group === g.key ? "bg-accent-solid text-accent-fg" : "border border-border bg-surface text-fg-muted hover:text-fg"
              }`}
            >
              {g.label} {tasks ? `(${counts.get(g.key) ?? 0})` : ""}
            </button>
          ))}
        </div>
        <select
          value={source}
          onChange={(e) => setSource(e.target.value)}
          aria-label="Filter by source"
          className="ml-auto rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-fg"
        >
          {SOURCES.map((s) => (
            <option key={s.key} value={s.key}>
              {s.label}
            </option>
          ))}
        </select>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search tasks or projects…"
          aria-label="Search tasks"
          className="w-56 rounded-md border border-border bg-surface px-3 py-1.5 text-xs text-fg placeholder:text-fg-faint focus-visible:border-accent"
        />
      </div>

      {tasks === null && !error ? (
        <SkeletonRows count={8} />
      ) : filtered.length === 0 ? (
        <EmptyState icon={ListChecks} title="No matching tasks" description="Nothing matches this filter yet. Try a different status or search term." />
      ) : (
        <Card>
          <ul className="divide-y divide-border">
            {filtered.map((task) => (
              <TaskRow key={task.id} task={task} showProject />
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
