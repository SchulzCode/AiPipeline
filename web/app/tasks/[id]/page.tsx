"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { API, api } from "@/lib/api";
import { agentLabel } from "@/lib/format";
import type { ActivityFeed, ActivityItem, ActivityStatus, Event, Project, Task } from "@/lib/types";
import { DiscoveryPanel } from "@/components/discovery-panel";
import { StatusBadge } from "@/components/status-badge";
import { TaskTimer } from "@/components/task-timer";

const stages = ["ROUTING", "PREPARING", "DISCOVERY", "PLANNING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "PR_OPEN", "CI", "MERGING", "POST_MERGE", "DONE"];

const TONES: Record<ActivityStatus, string> = {
  success: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  warning: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  error: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  info: "border-blue-400/30 bg-blue-400/10 text-blue-200",
};

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [activity, setActivity] = useState<ActivityFeed | null>(null);
  const [showTechnical, setShowTechnical] = useState(false);
  const [error, setError] = useState("");
  const activityRefresh = useRef<number | null>(null);

  const refreshActivity = useCallback(() => {
    if (activityRefresh.current) window.clearTimeout(activityRefresh.current);
    activityRefresh.current = window.setTimeout(() => {
      api.activity(id).then(setActivity).catch(() => undefined);
    }, 200);
  }, [id]);

  useEffect(() => {
    api.task(id).then((t) => {
      setTask(t);
      api.project(t.project_id).then(setProject).catch(() => undefined);
    }).catch((e) => setError(String(e)));
    api.events(id).then(setEvents).catch(() => undefined);
    api.activity(id).then(setActivity).catch(() => undefined);

    const stream = new EventSource(`${API}/tasks/${id}/stream`, { withCredentials: true });
    stream.addEventListener("task", (raw) => {
      const event = JSON.parse((raw as MessageEvent).data) as Event;
      setEvents((old) => old.some((x) => x.id === event.id) ? old : [...old, event]);
      if (event.kind === "core:status") api.task(id).then(setTask).catch(() => undefined);
      refreshActivity();
    });
    stream.onerror = () => api.task(id).then(setTask).catch(() => undefined);
    return () => {
      stream.close();
      if (activityRefresh.current) window.clearTimeout(activityRefresh.current);
    };
  }, [id, refreshActivity]);

  const currentIndex = useMemo(() => {
    if (!activity) return -1;
    for (let i = activity.items.length - 1; i >= 0; i--) {
      const idx = stages.indexOf(activity.items[i].category);
      if (idx >= 0) return idx;
    }
    return -1;
  }, [activity]);

  if (!task) return <div className="text-zinc-500">Loading task… {error}</div>;

  const stoppedEarly = ["BLOCKED", "FAILED", "CANCELLED", "NEEDS_INPUT"].includes(task.status);
  const repo = project?.repository_full_name;

  return (
    <div>
      <Link href={`/projects/${task.project_id}`} className="text-sm text-zinc-500 hover:text-white">← Project</Link>

      {/* 1. Status + timer */}
      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-sm text-zinc-500">{task.core_task_id || task.id}</div>
          <h1 className="mt-1 max-w-4xl text-3xl font-semibold">{task.title || task.prompt}</h1>
        </div>
        <StatusBadge status={task.status} />
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Info label="Agent" value={project ? agentLabel(project) : "Loading…"} />
        <Info label="Risk" value={task.risk || "Pending"} />
        <Info
          label="Runtime"
          value={<TaskTimer startedAt={task.started_at} endedAt={task.completed_at} notStartedLabel="Not started yet" />}
        />
        <Info
          label="Branch / PR"
          value={
            <span className="flex flex-col gap-0.5">
              <span className="truncate">{task.branch ? (repo ? <a className="hover:text-white underline decoration-white/20" href={`https://github.com/${repo}/tree/${task.branch}`} target="_blank" rel="noreferrer">{task.branch}</a> : task.branch) : "No branch yet"}</span>
              <span>{task.pr_number ? (repo ? <a className="hover:text-white underline decoration-white/20" href={`https://github.com/${repo}/pull/${task.pr_number}`} target="_blank" rel="noreferrer">PR #{task.pr_number}</a> : `PR #${task.pr_number}`) : "No pull request yet"}</span>
            </span>
          }
        />
      </div>

      {/* Blocked / failed / cancelled / needs-input banner */}
      {activity?.blocker && (
        <section className={`mt-6 rounded-2xl border p-5 ${["BLOCKED", "NEEDS_INPUT"].includes(task.status) ? "border-amber-400/30 bg-amber-400/10" : "border-rose-500/30 bg-rose-500/10"}`}>
          <h2 className={`font-semibold ${["BLOCKED", "NEEDS_INPUT"].includes(task.status) ? "text-amber-200" : "text-rose-200"}`}>
            Task {task.status === "BLOCKED" ? "blocked" : task.status === "CANCELLED" ? "cancelled" : task.status === "NEEDS_INPUT" ? "needs input" : "failed"}
          </h2>
          {activity.blocker.last_phase && (
            <div className="mt-1 text-sm text-zinc-300">Last completed step: {activity.blocker.last_phase}</div>
          )}
          <pre className="mt-2 whitespace-pre-wrap break-words text-sm text-zinc-100/80">{activity.blocker.reason}</pre>
        </section>
      )}

      {/* 2. Current activity */}
      {activity?.current && (
        <section className="mt-6 rounded-2xl border border-blue-400/25 bg-blue-400/[0.06] p-5">
          <div className="text-xs font-semibold uppercase tracking-wider text-blue-300">Currently</div>
          <div className="mt-1 text-lg font-semibold">{activity.current.title}</div>
          <div className="mt-1 max-w-3xl text-sm text-zinc-300">{activity.current.summary}</div>
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm text-zinc-400">
            <span>Agent: <span className="text-zinc-200">{activity.current.agent_label}</span></span>
            <span>Phase duration: <span className="text-zinc-200"><TaskTimer startedAt={activity.current.started_at} /></span></span>
            {activity.current.next_step && <span>Next: <span className="text-zinc-200">{activity.current.next_step}</span></span>}
          </div>
        </section>
      )}

      {/* 3. Progress / lifecycle stages, or the discovery-specific panel */}
      {task.source === "discovery" ? (
        <DiscoveryPanel taskId={task.id} />
      ) : (
        <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <h2 className="font-semibold">Pipeline</h2>
          <div className="mt-5 grid gap-2 md:grid-cols-4 xl:grid-cols-6">
            {stages.map((stage, index) => {
              const done = task.status === "DONE" || index < currentIndex;
              const active = index === currentIndex && !done;
              const stoppedHere = active && stoppedEarly;
              const stoppedWarn = stoppedHere && task.status === "NEEDS_INPUT";
              const tone = done
                ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
                : stoppedWarn
                  ? "border-amber-400/30 bg-amber-400/10 text-amber-200"
                  : stoppedHere
                    ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
                    : active
                      ? "border-blue-400/40 bg-blue-400/10 text-blue-200"
                      : "border-white/10 text-zinc-600";
              const marker = done ? "✓ " : stoppedHere ? "✕ " : active ? "● " : "○ ";
              return <div key={stage} className={`rounded-xl border p-3 text-xs font-semibold ${tone}`}>{marker}{stage}</div>;
            })}
          </div>
        </section>
      )}

      {/* 3b. Planner output */}
      {activity?.checks.plan && (
        <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <h2 className="font-semibold">Implementation plan</h2>
          <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words text-sm text-zinc-300">{activity.checks.plan.plan}</pre>
        </section>
      )}

      {/* 4. Activity timeline */}
      <section className="mt-6">
        <h2 className="mb-3 text-lg font-semibold">Activity</h2>
        <div className="space-y-3">
          {activity?.items.slice().reverse().map((item, index) => <ActivityCard key={`${item.timestamp}-${index}`} item={item} />)}
          {activity && !activity.items.length && <div className="rounded-2xl border border-white/10 bg-black/30 p-5 text-zinc-500">Waiting for the pipeline to start…</div>}
          {!activity && <div className="rounded-2xl border border-white/10 bg-black/30 p-5 text-zinc-500">Loading activity…</div>}
        </div>
      </section>

      {/* 5. Checks / review / CI summary */}
      {activity && (activity.checks.checks.length > 0 || activity.checks.review || activity.checks.security_review || activity.checks.ci) && (
        <section className="mt-6 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <h2 className="font-semibold">Checks &amp; review</h2>
          <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {activity.checks.checks.length > 0 && (
              <div>
                <div className="text-xs uppercase tracking-wider text-zinc-600">Local checks</div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {activity.checks.checks.map((check) => (
                    <span key={`${check.type}:${check.name}`} className={`rounded-full border px-2 py-0.5 text-xs ${check.status === "PASS" ? TONES.success : TONES.error}`}>{check.name}</span>
                  ))}
                </div>
              </div>
            )}
            {activity.checks.review && <SummaryTile label="Review" status={activity.checks.review.status} value={activity.checks.review.result} />}
            {activity.checks.security_review && <SummaryTile label="Security review" status={activity.checks.security_review.status} value={activity.checks.security_review.result} />}
            {activity.checks.ci && (
              <SummaryTile
                label="CI"
                status={activity.checks.ci.failed > 0 ? "warning" : activity.checks.ci.total === 0 ? "info" : "success"}
                value={`${activity.checks.ci.passed}/${activity.checks.ci.total} passed`}
              />
            )}
          </div>
        </section>
      )}

      {/* 6. Technical details */}
      <section className="mt-6">
        <button
          type="button"
          onClick={() => setShowTechnical((v) => !v)}
          className="text-sm font-semibold text-zinc-400 hover:text-white"
        >
          {showTechnical ? "▾" : "▸"} Technical details ({events.length} raw event{events.length === 1 ? "" : "s"}, {(task.input_tokens + task.output_tokens).toLocaleString()} tokens)
        </button>
        {showTechnical && (
          <div className="mt-3 overflow-hidden rounded-2xl border border-white/10 bg-black/30">
            {events.slice().reverse().map((event) => (
              <div key={event.id} className="grid gap-2 border-b border-white/[0.06] px-4 py-3 last:border-0 md:grid-cols-[12rem_1fr]">
                <div>
                  <div className="text-xs font-semibold text-blue-200">{event.kind}</div>
                  <div className="mt-1 text-xs text-zinc-600">{new Date(event.created_at).toLocaleString()}</div>
                </div>
                <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs text-zinc-400">{event.detail || ""}</pre>
              </div>
            ))}
            {!events.length && <div className="p-5 text-zinc-500">Waiting for worker events…</div>}
          </div>
        )}
      </section>
    </div>
  );
}

function ActivityCard({ item }: { item: ActivityItem }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="font-semibold">{item.title}</div>
        <div className="flex items-center gap-2 text-xs text-zinc-500">
          {typeof item.duration_seconds === "number" && <span>{formatShortDuration(item.duration_seconds)}</span>}
          <span>{new Date(item.timestamp).toLocaleString()}</span>
        </div>
      </div>
      {item.summary && <div className="mt-1 text-sm text-zinc-400">{item.summary}</div>}
      {item.result && (
        <div className={`mt-2 inline-block rounded-lg border px-2.5 py-1 text-xs ${TONES[item.status]}`}>
          Result: {item.result}
        </div>
      )}
      {item.next_step && <div className="mt-2 text-xs text-zinc-500">Next: {item.next_step}</div>}
    </div>
  );
}

function SummaryTile({ label, status, value }: { label: string; status: ActivityStatus; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-zinc-600">{label}</div>
      <div className={`mt-2 inline-block rounded-lg border px-2.5 py-1 text-xs ${TONES[status]}`}>{value}</div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4">
      <div className="text-xs uppercase tracking-wider text-zinc-600">{label}</div>
      <div className="mt-1 font-medium">{value}</div>
    </div>
  );
}

function formatShortDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return minutes > 0 ? `${minutes}m ${secs}s` : `${secs}s`;
}
