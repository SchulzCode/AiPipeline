"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { API, api } from "@/lib/api";
import type { Event, Project, Task } from "@/lib/types";
import { StatusBadge } from "@/components/status-badge";

const stages = ["ROUTING", "PREPARING", "DISCOVERY", "PLANNING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "PR_OPEN", "CI", "MERGING", "POST_MERGE", "DONE"];

export default function TaskPage() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [events, setEvents] = useState<Event[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api.task(id).then((t) => {
      setTask(t);
      api.project(t.project_id).then(setProject).catch(() => undefined);
    }).catch((e) => setError(String(e)));
    api.events(id).then(setEvents).catch(() => undefined);
    const stream = new EventSource(`${API}/tasks/${id}/stream`, { withCredentials: true });
    stream.addEventListener("task", (raw) => {
      const event = JSON.parse((raw as MessageEvent).data) as Event;
      setEvents((old) => old.some((x) => x.id === event.id) ? old : [...old, event]);
      if (event.kind === "core:status") api.task(id).then(setTask).catch(() => undefined);
    });
    stream.onerror = () => api.task(id).then(setTask).catch(() => undefined);
    return () => stream.close();
  }, [id]);

  const currentIndex = useMemo(() => task ? Math.max(0, stages.indexOf(task.status)) : 0, [task]);
  if (!task) return <div className="text-zinc-500">Loading task… {error}</div>;
  return (
    <div>
      <Link href={`/projects/${task.project_id}`} className="text-sm text-zinc-500 hover:text-white">← Project</Link>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-4"><div><div className="text-sm text-zinc-500">{task.core_task_id || task.id}</div><h1 className="mt-1 max-w-4xl text-3xl font-semibold">{task.title || task.prompt}</h1></div><StatusBadge status={task.status} /></div>
      <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-5"><Info label="Agent" value={project ? `${project.agent} · ${project.model || "Default"}` : "Loading…"} /><Info label="Risk" value={task.risk || "Pending"} /><Info label="Context" value={task.context_class || "Pending"} /><Info label="Tokens" value={(task.input_tokens + task.output_tokens).toLocaleString()} /><Info label="Pull request" value={task.pr_number ? `#${task.pr_number}` : "Not opened"} /></div>

      <section className="mt-8 rounded-2xl border border-white/10 bg-white/[0.03] p-5"><h2 className="font-semibold">Pipeline</h2><div className="mt-5 grid gap-2 md:grid-cols-4 xl:grid-cols-6">{stages.map((stage, index) => { const done = task.status === "DONE" || index < currentIndex; const active = stage === task.status; return <div key={stage} className={`rounded-xl border p-3 text-xs font-semibold ${done ? "border-emerald-500/25 bg-emerald-500/10 text-emerald-300" : active ? "border-blue-400/40 bg-blue-400/10 text-blue-200" : "border-white/10 text-zinc-600"}`}>{done ? "✓ " : active ? "● " : "○ "}{stage}</div>; })}</div></section>

      {task.error && <section className="mt-6 rounded-2xl border border-rose-500/30 bg-rose-500/10 p-5"><h2 className="font-semibold text-rose-200">Task stopped</h2><pre className="mt-2 whitespace-pre-wrap text-sm text-rose-100/80">{task.error}</pre></section>}

      <section className="mt-6"><h2 className="mb-3 text-lg font-semibold">Event stream</h2><div className="overflow-hidden rounded-2xl border border-white/10 bg-black/30">{events.slice().reverse().map((event) => <div key={event.id} className="grid gap-2 border-b border-white/[0.06] px-4 py-3 last:border-0 md:grid-cols-[12rem_1fr]"><div><div className="text-xs font-semibold text-blue-200">{event.kind}</div><div className="mt-1 text-xs text-zinc-600">{new Date(event.created_at).toLocaleString()}</div></div><pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs text-zinc-400">{event.detail || ""}</pre></div>)}{!events.length && <div className="p-5 text-zinc-500">Waiting for worker events…</div>}</div></section>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border border-white/10 bg-white/[0.03] p-4"><div className="text-xs uppercase tracking-wider text-zinc-600">{label}</div><div className="mt-1 font-medium">{value}</div></div>; }
