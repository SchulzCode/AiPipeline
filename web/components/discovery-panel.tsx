"use client";

import { useEffect, useState } from "react";
import { CompassTool, MagnifyingGlass } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { DiscoverySummary, Task } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner } from "@/components/ui/error-banner";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { DiscoveryStatusBadge } from "@/components/ui/badge";
import { TaskRow } from "@/components/task-row";

export function DiscoveryPanel({ taskId }: { taskId: string }) {
  const [summary, setSummary] = useState<DiscoverySummary | null>(null);
  const [handoffTasks, setHandoffTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const [discoveryResult, handoffResult] = await Promise.all([api.discovery(taskId), api.handoffTasks(taskId)]);
        if (cancelled) return;
        setSummary(discoveryResult);
        setHandoffTasks(handoffResult);
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [taskId]);

  if (error) return <ErrorBanner message={error} />;
  if (!summary) return <Skeleton className="h-40 w-full" />;

  if (summary.status === "pending") {
    return (
      <Card className="border-status-active/30 bg-status-active/[0.04]">
        <CardBody className="flex items-center gap-3">
          <MagnifyingGlass size={20} weight="duotone" className="shrink-0 text-status-active" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium text-status-active">Discovering</p>
            <p className="mt-0.5 text-xs text-fg-muted">A read-only agent is exploring the repository for feature candidates. Nothing is implemented automatically.</p>
          </div>
        </CardBody>
      </Card>
    );
  }

  const ranked = summary.candidates.slice().sort((a, b) => (a.rank ?? 999999) - (b.rank ?? 999999));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Discovery summary" />
        <CardBody className="flex flex-wrap gap-2 text-xs">
          <SummaryPill label={`${summary.created.length} created`} tone="done" />
          <SummaryPill label={`${summary.duplicates.length} duplicate`} tone="attention" />
          <SummaryPill label={`${summary.failed.length} failed`} tone="failed" />
          <SummaryPill label={`${summary.handoff_issue_numbers.length} handed off`} tone="active" />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Candidates" />
        <CardBody className="space-y-2">
          {ranked.length === 0 ? (
            <EmptyState icon={CompassTool} title="No candidates were proposed" />
          ) : (
            ranked.map((candidate) => (
              <div key={candidate.key} className="rounded-md border border-border bg-surface-sunken p-4">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="text-xs text-fg-faint">
                      Rank {candidate.rank ?? "—"} · score {candidate.score.toFixed(2)}
                    </p>
                    <p className="mt-1 text-sm font-medium text-fg">{candidate.title}</p>
                  </div>
                  <DiscoveryStatusBadge status={candidate.status} />
                </div>
                <p className="mt-2 text-sm text-fg-muted">{candidate.summary}</p>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-fg-faint">
                  <span>{candidate.risk} risk</span>
                  <span>{candidate.context_class} context</span>
                  {candidate.duplicate_of && <span>Duplicate of {candidate.duplicate_of}</span>}
                  {candidate.issue_number && candidate.issue_url && (
                    <a className="text-accent hover:text-accent-hover" href={candidate.issue_url} target="_blank" rel="noreferrer">
                      Issue #{candidate.issue_number}
                    </a>
                  )}
                  {candidate.error && <span className="text-status-failed">{candidate.error}</span>}
                  {candidate.handoff && <span className="text-status-done">Handed off for implementation</span>}
                </div>
              </div>
            ))
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Handoff tasks" />
        {handoffTasks.length === 0 ? (
          <CardBody>
            <EmptyState icon={CompassTool} title="No candidates were handed off" description="Nothing was eligible for automatic implementation." />
          </CardBody>
        ) : (
          <ul className="divide-y divide-border">
            {handoffTasks.map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function SummaryPill({ label, tone }: { label: string; tone: "done" | "attention" | "failed" | "active" }) {
  const styles: Record<typeof tone, string> = {
    done: "border-status-done/30 bg-status-done/10 text-status-done",
    attention: "border-status-attention/30 bg-status-attention/10 text-status-attention",
    failed: "border-status-failed/30 bg-status-failed/10 text-status-failed",
    active: "border-status-active/30 bg-status-active/10 text-status-active",
  };
  return <span className={`rounded-pill border px-2.5 py-1 ${styles[tone]}`}>{label}</span>;
}
