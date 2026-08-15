import type { Project } from "./types";

const AGENT_LABELS: Record<string, string> = { claude: "Claude", codex: "Codex" };

export function agentLabel(project: { agent: string; model?: string | null }): string {
  const base = AGENT_LABELS[project.agent] || project.agent;
  return project.model ? `${base} · ${project.model}` : base;
}

export function projectAgentLabel(project: Pick<Project, "agent" | "model">): string {
  return agentLabel(project);
}

/** Absolute timestamp for detail views, e.g. "Aug 15, 14:32". */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

/** Relative "time ago" for scannable lists, e.g. "3m ago", "yesterday". */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const then = new Date(iso).getTime();
  const diffSeconds = Math.round((now - then) / 1000);
  if (diffSeconds < 5) return "just now";
  if (diffSeconds < 60) return `${diffSeconds}s ago`;
  const minutes = Math.round(diffSeconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return formatTimestamp(iso);
}

/** Compact token count, e.g. 12400 -> "12.4k". */
export function formatTokenCount(count: number): string {
  if (count < 1000) return String(count);
  if (count < 1_000_000) return `${(count / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return `${(count / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}
