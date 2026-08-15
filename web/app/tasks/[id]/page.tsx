"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, ArrowSquareOut, CaretDown, CaretRight, GitBranch, WarningCircle } from "@phosphor-icons/react";
import { api, streamUrl } from "@/lib/api";
import { agentLabel, formatTimestamp, formatTokenCount } from "@/lib/format";
import { activityTone, TONE_META, type Tone } from "@/lib/status";
import type { ActivityFeed, ActivityItem, Event, Project, Task } from "@/lib/types";
import { DiscoveryPanel } from "@/components/discovery-panel";
import { TaskStatusBadge } from "@/components/ui/badge";
import { TaskTimer } from "@/components/task-timer";
import { PipelineStages } from "@/components/pipeline-stages";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Skeleton } from "@/components/ui/skeleton";

const BLOCKER_LABEL: Record<string, string> = {
  BLOCKED: "blocked",
  CANCELLED: "cancelled",
  NEEDS_INPUT: "needs input",
  FAILED: "failed",
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
    api
      .task(id)
      .then((t) => {
        setTask(t);
        api.project(t.project_id).then(setProject).catch(() => undefined);
      })
      .catch((e) => setError(String(e)));
    api.events(id).then(setEvents).catch(() => undefined);
    api.activity(id).then(setActivity).catch(() => undefined);

    const stream = new EventSource(streamUrl(id), { withCredentials: true });
    stream.addEventListener("task", (raw) => {
      const event = JSON.parse((raw as MessageEvent).data) as Event;
      setEvents((old) => (old.some((x) => x.id === event.id) ? old : [...old, event]));
      if (event.kind === "core:status") api.task(id).then(setTask).catch(() => undefined);
      refreshActivity();
    });
    stream.onerror = () => api.task(id).then(setTask).catch(() => undefined);
    return () => {
      stream.close();
      if (activityRefresh.current) window.clearTimeout(activityRefresh.current);
    };
  }, [id, refreshActivity]);

  if (!task && !error) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-2/3" />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (!task) return <ErrorBanner message={error} />;

  const repo = project?.repository_full_name;
  const totalTokens = task.input_tokens + task.output_tokens;

  return (
    <div className="animate-enter space-y-6">
      <Link href={`/projects/${task.project_id}`} className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg">
        <ArrowLeft size={13} aria-hidden="true" />
        Project
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs text-fg-faint">{task.core_task_id || task.id}</p>
          <h1 className="mt-1 max-w-4xl text-xl font-semibold tracking-tight text-fg">{task.title || task.prompt}</h1>
        </div>
        <TaskStatusBadge status={task.status} />
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Info label="Agent" value={project ? agentLabel(project) : "Loading…"} />
        <Info label="Risk" value={task.risk || "Pending"} />
        <Info label="Runtime" value={<TaskTimer startedAt={task.started_at} endedAt={task.completed_at} notStartedLabel="Not started yet" />} />
        <Info
          label="Branch / PR"
          value={
            <span className="flex flex-col gap-0.5">
              <span className="flex items-center gap-1 truncate">
                <GitBranch size={12} className="shrink-0 text-fg-faint" aria-hidden="true" />
                {task.branch ? (
                  repo ? (
                    <a className="truncate hover:text-accent" href={`https://github.com/${repo}/tree/${task.branch}`} target="_blank" rel="noreferrer">
                      {task.branch}
                    </a>
                  ) : (
                    task.branch
                  )
                ) : (
                  "No branch yet"
                )}
              </span>
              <span>
                {task.pr_number ? (
                  repo ? (
                    <a className="inline-flex items-center gap-1 hover:text-accent" href={`https://github.com/${repo}/pull/${task.pr_number}`} target="_blank" rel="noreferrer">
                      PR #{task.pr_number}
                      <ArrowSquareOut size={11} aria-hidden="true" />
                    </a>
                  ) : (
                    `PR #${task.pr_number}`
                  )
                ) : (
                  "No pull request yet"
                )}
              </span>
            </span>
          }
        />
        <Info label="Tokens" value={<span className="tabular-nums">{formatTokenCount(totalTokens)}</span>} />
      </div>

      {activity?.blocker ? (
        <Card className={["BLOCKED", "NEEDS_INPUT"].includes(task.status) ? "border-status-attention/30 bg-status-attention/[0.06]" : "border-status-failed/30 bg-status-failed/[0.06]"}>
          <CardBody>
            <div className="flex items-center gap-2">
              <WarningCircle size={18} weight="bold" className={["BLOCKED", "NEEDS_INPUT"].includes(task.status) ? "text-status-attention" : "text-status-failed"} aria-hidden="true" />
              <h2 className={`text-sm font-semibold ${["BLOCKED", "NEEDS_INPUT"].includes(task.status) ? "text-status-attention" : "text-status-failed"}`}>
                Task {BLOCKER_LABEL[task.status] ?? "stopped"}
                {task.failure_category ? ` · ${task.failure_category}` : ""}
              </h2>
            </div>
            {activity.blocker.last_phase ? <p className="mt-2 text-sm text-fg-muted">Last completed step: {activity.blocker.last_phase}</p> : null}
            <p className="mt-2 whitespace-pre-wrap break-words text-sm text-fg">{activity.blocker.reason}</p>
          </CardBody>
        </Card>
      ) : null}

      {activity?.current ? (
        <Card className="border-status-active/30 bg-status-active/[0.04]">
          <CardBody>
            <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-status-active">
              <span className="h-1.5 w-1.5 rounded-full bg-status-active animate-live-pulse" aria-hidden="true" />
              Currently
            </p>
            <p className="mt-1.5 text-base font-semibold text-fg">{activity.current.title}</p>
            {activity.current.summary ? <p className="mt-1 max-w-3xl text-sm text-fg-muted">{activity.current.summary}</p> : null}
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1.5 text-xs text-fg-muted">
              <span>
                Agent role: <span className="text-fg">{activity.current.agent_label}</span>
              </span>
              <span>
                Phase runtime: <span className="tabular-nums text-fg"><TaskTimer startedAt={activity.current.started_at} /></span>
              </span>
              {activity.current.next_step ? (
                <span>
                  Next: <span className="text-fg">{activity.current.next_step}</span>
                </span>
              ) : null}
            </div>
          </CardBody>
        </Card>
      ) : null}

      {task.source === "discovery" ? (
        <DiscoveryPanel taskId={task.id} />
      ) : (
        <Card>
          <CardHeader title="Pipeline" description="Routing through implementation, review, CI, and merge." />
          <CardBody>
            <PipelineStages activity={activity} taskStatus={task.status} />
          </CardBody>
        </Card>
      )}

      {activity?.checks.plan ? (
        <Card>
          <CardHeader title="Implementation plan" />
          <CardBody>
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-fg-muted">{activity.checks.plan.plan}</pre>
          </CardBody>
        </Card>
      ) : null}

      {activity && (activity.checks.checks.length > 0 || activity.checks.review || activity.checks.security_review || activity.checks.ci) ? (
        <Card>
          <CardHeader title="Checks & review" />
          <CardBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {activity.checks.checks.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-fg-muted">Local checks</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {activity.checks.checks.map((check) => (
                    <ToneChip key={`${check.type}:${check.name}`} tone={check.status === "PASS" ? "done" : "failed"} label={check.name} />
                  ))}
                </div>
              </div>
            ) : null}
            {activity.checks.review ? <SummaryTile label="Review" tone={activityTone(activity.checks.review.status)} value={activity.checks.review.result} /> : null}
            {activity.checks.security_review ? <SummaryTile label="Security review" tone={activityTone(activity.checks.security_review.status)} value={activity.checks.security_review.result} /> : null}
            {activity.checks.ci ? (
              <SummaryTile
                label="CI"
                tone={activity.checks.ci.failed > 0 ? "attention" : activity.checks.ci.total === 0 ? "active" : "done"}
                value={`${activity.checks.ci.passed}/${activity.checks.ci.total} passed`}
              />
            ) : null}
          </CardBody>
        </Card>
      ) : null}

      <section aria-labelledby="activity-heading">
        <h2 id="activity-heading" className="mb-3 text-sm font-semibold text-fg">
          Activity
        </h2>
        <div className="space-y-2">
          {activity?.items
            .slice()
            .reverse()
            .map((item, index) => <ActivityCard key={`${item.timestamp}-${index}`} item={item} />)}
          {activity && activity.items.length === 0 ? <Card className="p-5 text-sm text-fg-muted">Waiting for the pipeline to start…</Card> : null}
          {!activity ? <Skeleton className="h-24 w-full" /> : null}
        </div>
      </section>

      <section>
        <button type="button" onClick={() => setShowTechnical((v) => !v)} className="inline-flex items-center gap-1.5 text-sm font-medium text-fg-muted hover:text-fg">
          {showTechnical ? <CaretDown size={13} aria-hidden="true" /> : <CaretRight size={13} aria-hidden="true" />}
          Technical details ({events.length} raw event{events.length === 1 ? "" : "s"}, {totalTokens.toLocaleString()} tokens)
        </button>
        {showTechnical ? (
          <Card className="mt-3 overflow-hidden">
            {events.length === 0 ? (
              <p className="p-5 text-sm text-fg-muted">Waiting for worker events…</p>
            ) : (
              events
                .slice()
                .reverse()
                .map((event) => (
                  <div key={event.id} className="grid gap-2 border-b border-border px-4 py-3 last:border-0 md:grid-cols-[12rem_1fr]">
                    <div>
                      <p className="font-mono text-xs font-medium text-status-active">{event.kind}</p>
                      <p className="mt-1 text-xs text-fg-faint">{formatTimestamp(event.created_at)}</p>
                    </div>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-fg-muted">{event.detail || ""}</pre>
                  </div>
                ))
            )}
          </Card>
        ) : null}
      </section>
    </div>
  );
}

function ActivityCard({ item }: { item: ActivityItem }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sm font-semibold text-fg">{item.title}</p>
        <div className="flex shrink-0 items-center gap-2 text-xs text-fg-faint">
          {typeof item.duration_seconds === "number" ? <span className="tabular-nums">{formatShortDuration(item.duration_seconds)}</span> : null}
          <span>{formatTimestamp(item.timestamp)}</span>
        </div>
      </div>
      {item.summary ? <p className="mt-1 text-sm text-fg-muted">{item.summary}</p> : null}
      {item.result ? (
        <div className="mt-2">
          <ToneChip tone={activityTone(item.status)} label={`Result: ${item.result}`} />
        </div>
      ) : null}
      {item.next_step ? <p className="mt-2 text-xs text-fg-faint">Next: {item.next_step}</p> : null}
    </Card>
  );
}

function ToneChip({ tone, label }: { tone: Tone; label: string }) {
  const meta = TONE_META[tone];
  return <span className={`inline-block rounded-md border px-2 py-1 text-xs ${meta.bg} ${meta.border} ${meta.text}`}>{label}</span>;
}

function SummaryTile({ label, tone, value }: { label: string; tone: Tone; value: string }) {
  return (
    <div>
      <p className="text-xs font-medium text-fg-muted">{label}</p>
      <div className="mt-2">
        <ToneChip tone={tone} label={value} />
      </div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-md border border-border bg-surface p-3.5">
      <p className="text-xs font-medium text-fg-muted">{label}</p>
      <div className="mt-1 text-sm text-fg">{value}</div>
    </div>
  );
}

function formatShortDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return minutes > 0 ? `${minutes}m ${secs}s` : `${secs}s`;
}
