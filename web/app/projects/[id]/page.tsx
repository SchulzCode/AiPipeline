"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";

import { StatusBadge } from "@/components/status-badge";
import { api } from "@/lib/api";
import { agentLabel } from "@/lib/format";
import type { Issue, Project, Task } from "@/lib/types";

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [projectResult, taskResults] = await Promise.all([
        api.project(id),
        api.tasks(id),
      ]);

      setProject(projectResult);
      setTasks(taskResults);

      try {
        const issueResults = await api.issues(id);
        setIssues(issueResults);
      } catch {
        setIssues([]);
      }
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    // Schedule the initial refresh instead of invoking a state-updating
    // function synchronously from the effect body.
    const initialRefresh = window.setTimeout(() => {
      void refresh();
    }, 0);

    const refreshTimer = window.setInterval(() => {
      void refresh();
    }, 5000);

    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(refreshTimer);
    };
  }, [refresh]);

  async function submit(e: FormEvent) {
    e.preventDefault();

    if (!prompt.trim()) {
      return;
    }

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

    try {
      const task = await api.createDiscoveryTask(id);
      router.push(`/tasks/${task.id}`);
    } catch (e) {
      setError(String(e));
    }
  }

  if (!project) {
    return (
      <div className="text-zinc-500">
        Loading project…
      </div>
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div>
          <div className="text-sm text-zinc-500">
            {project.repository_full_name || project.local_path}
          </div>

          <h1 className="mt-1 text-4xl font-semibold">
            {project.name}
          </h1>

          <div className="mt-3 flex gap-3">
            <StatusBadge status={project.status} />

            <span className="text-sm text-zinc-500">
              {agentLabel(project)} · {project.default_branch}
            </span>
          </div>
        </div>
      </div>

      <form
        onSubmit={submit}
        className="mt-8 rounded-2xl border border-blue-400/20 bg-blue-400/[0.05] p-5"
      >
        <label className="text-sm font-semibold">
          New autonomous task
        </label>

        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          className="mt-3 w-full resize-y rounded-xl border border-white/10 bg-black/30 p-3 outline-none focus:border-blue-400"
          placeholder="Describe the desired result. The pipeline will handle routing, implementation, review, CI and guarded merge."
        />

        <div className="mt-3 flex justify-end">
          <button
            disabled={busy || !prompt.trim()}
            className="rounded-xl bg-white px-4 py-2.5 font-semibold text-black disabled:opacity-40"
          >
            {busy ? "Queueing…" : "Run task"}
          </button>
        </div>
      </form>

      {project.repository_full_name && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-white/[0.03] p-5">
          <div>
            <div className="text-sm font-semibold">Feature discovery</div>
            <div className="mt-1 text-sm text-zinc-500">
              Explore the repository read-only and file ranked, deduplicated feature candidates as GitHub issues. Nothing is implemented automatically unless auto-implementation is configured.
            </div>
          </div>

          <button
            type="button"
            onClick={runDiscovery}
            className="rounded-xl border border-white/15 px-4 py-2.5 font-semibold hover:bg-white/10"
          >
            Discover features
          </button>
        </div>
      )}

      {error && (
        <div className="mt-4 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          {error}
        </div>
      )}

      <div className="mt-8 grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <section>
          <h2 className="mb-3 text-lg font-semibold">
            Tasks
          </h2>

          <div className="space-y-2">
            {tasks.map((task) => (
              <Link
                key={task.id}
                href={`/tasks/${task.id}`}
                className="flex items-center justify-between gap-4 rounded-xl border border-white/10 bg-white/[0.03] p-4"
              >
                <div className="min-w-0">
                  <div className="truncate font-medium">
                    {task.title || task.prompt}
                  </div>

                  <div className="mt-1 text-xs text-zinc-500">
                    {task.risk
                      ? `${task.risk} risk · `
                      : ""}
                    {task.source}
                  </div>
                </div>

                <StatusBadge status={task.status} />
              </Link>
            ))}

            {!tasks.length && (
              <div className="rounded-xl border border-dashed border-white/10 p-5 text-zinc-500">
                No tasks yet.
              </div>
            )}
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">
            Open GitHub issues
          </h2>

          <div className="max-h-[36rem] space-y-2 overflow-auto">
            {issues.map((issue) => (
              <div
                key={issue.number}
                className="rounded-xl border border-white/10 bg-white/[0.03] p-4"
              >
                <div className="text-xs text-zinc-500">
                  #{issue.number}
                </div>

                <div className="mt-1 font-medium">
                  {issue.title}
                </div>

                <button
                  type="button"
                  onClick={() => runIssue(issue.number)}
                  className="mt-3 rounded-lg border border-white/15 px-3 py-1.5 text-sm hover:bg-white/10"
                >
                  Run with AIpipe
                </button>
              </div>
            ))}

            {!issues.length && (
              <div className="rounded-xl border border-dashed border-white/10 p-5 text-zinc-500">
                No issues available or GitHub App not configured.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}