"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import type { DiscoverySummary, FeatureCandidate, Task } from "@/lib/types";

const STATUS_TONE: Record<FeatureCandidate["status"], string> = {
  proposed: "border-blue-400/30 bg-blue-400/10 text-blue-200",
  created: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  duplicate: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  failed: "border-rose-500/30 bg-rose-500/10 text-rose-300",
};

export function DiscoveryPanel({ taskId }: { taskId: string }) {
  const [summary, setSummary] = useState<DiscoverySummary | null>(null);
  const [handoffTasks, setHandoffTasks] = useState<Task[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function refresh() {
      try {
        const [discoveryResult, handoffResult] = await Promise.all([
          api.discovery(taskId),
          api.handoffTasks(taskId),
        ]);
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

  if (error) {
    return (
      <div className="mt-6 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-5 text-sm text-rose-200">
        {error}
      </div>
    );
  }

  if (!summary) {
    return <div className="mt-6 rounded-2xl border border-white/10 bg-black/30 p-5 text-zinc-500">Loading discovery results…</div>;
  }

  if (summary.status === "pending") {
    return (
      <section className="mt-6 rounded-2xl border border-blue-400/25 bg-blue-400/[0.06] p-5">
        <div className="text-xs font-semibold uppercase tracking-wider text-blue-300">Discovering</div>
        <div className="mt-1 text-sm text-zinc-300">
          A read-only agent is exploring the repository for feature candidates. Nothing is implemented automatically.
        </div>
      </section>
    );
  }

  const ranked = summary.candidates.slice().sort((a, b) => (a.rank ?? 999999) - (b.rank ?? 999999));

  return (
    <div className="mt-6 space-y-6">
      <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="font-semibold">Discovery summary</h2>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-emerald-300">{summary.created.length} created</span>
          <span className="rounded-full border border-amber-400/30 bg-amber-400/10 px-2.5 py-1 text-amber-200">{summary.duplicates.length} duplicate</span>
          <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2.5 py-1 text-rose-300">{summary.failed.length} failed</span>
          <span className="rounded-full border border-blue-400/30 bg-blue-400/10 px-2.5 py-1 text-blue-200">{summary.handoff_issue_numbers.length} handed off</span>
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="font-semibold">Candidates</h2>
        <div className="mt-4 space-y-2">
          {ranked.map((candidate) => (
            <div key={candidate.key} className="rounded-xl border border-white/10 bg-black/20 p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <div className="text-xs text-zinc-500">Rank {candidate.rank ?? "—"} · score {candidate.score.toFixed(2)}</div>
                  <div className="mt-1 font-medium">{candidate.title}</div>
                </div>
                <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${STATUS_TONE[candidate.status]}`}>{candidate.status}</span>
              </div>
              <div className="mt-2 text-sm text-zinc-400">{candidate.summary}</div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
                <span>{candidate.risk} risk</span>
                <span>{candidate.context_class} context</span>
                {candidate.duplicate_of && <span>Duplicate of {candidate.duplicate_of}</span>}
                {candidate.issue_number && candidate.issue_url && (
                  <a
                    className="text-blue-300 underline decoration-white/20 hover:text-white"
                    href={candidate.issue_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Issue #{candidate.issue_number}
                  </a>
                )}
                {candidate.error && <span className="text-rose-300">{candidate.error}</span>}
                {candidate.handoff && <span className="text-emerald-300">Handed off for implementation</span>}
              </div>
            </div>
          ))}
          {!ranked.length && (
            <div className="rounded-xl border border-dashed border-white/10 p-5 text-zinc-500">No candidates were proposed.</div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-white/[0.03] p-5">
        <h2 className="font-semibold">Handoff tasks</h2>
        <div className="mt-4 space-y-2">
          {handoffTasks.map((task) => (
            <Link
              key={task.id}
              href={`/tasks/${task.id}`}
              className="flex items-center justify-between gap-4 rounded-xl border border-white/10 bg-black/20 p-4"
            >
              <div className="min-w-0">
                <div className="truncate font-medium">{task.title || task.prompt}</div>
                <div className="mt-1 text-xs text-zinc-500">Issue #{task.source_reference}</div>
              </div>
              <StatusBadge status={task.status} />
            </Link>
          ))}
          {!handoffTasks.length && (
            <div className="rounded-xl border border-dashed border-white/10 p-5 text-zinc-500">
              No candidates were handed off for automatic implementation.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
