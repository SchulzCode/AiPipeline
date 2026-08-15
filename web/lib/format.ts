import type { Project } from "./types";

const AGENT_LABELS: Record<string, string> = { claude: "Claude", codex: "Codex" };

export function agentLabel(project: Pick<Project, "agent" | "model">): string {
  const base = AGENT_LABELS[project.agent] || project.agent;
  return project.model ? `${base} · ${project.model}` : base;
}
