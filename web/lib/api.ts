import type {
  ActivityFeed,
  AgentModels,
  DiscoverySummary,
  Event,
  Installation,
  Issue,
  Project,
  ProjectConfig,
  ProjectConfigPatch,
  Repository,
  SystemHealth,
  Task,
  TaskWithProject,
  User,
} from "./types";

export const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `${response.status} ${response.statusText}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type TaskListFilter = { status?: string; project_id?: string; source?: string; limit?: number };

function query(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") usp.set(key, String(value));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  me: () => request<User>("/auth/me"),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  projects: () => request<Project[]>("/projects"),
  project: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (data: object) => request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  updateProject: (id: string, patch: { name?: string; agent?: string; model?: string | null; enabled?: boolean }) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  agentModels: () => request<AgentModels>("/agents/models"),
  installations: () => request<Installation[]>("/github/installations"),
  installationRepos: (id: number) => request<Repository[]>(`/github/installations/${id}/repositories`),
  tasks: (projectId: string) => request<Task[]>(`/projects/${projectId}/tasks`),
  allTasks: (filter: TaskListFilter = {}) => request<TaskWithProject[]>(`/tasks${query(filter)}`),
  task: (id: string) => request<Task>(`/tasks/${id}`),
  events: (id: string) => request<Event[]>(`/tasks/${id}/events`),
  activity: (id: string) => request<ActivityFeed>(`/tasks/${id}/activity`),
  issues: (projectId: string) => request<Issue[]>(`/projects/${projectId}/issues`),
  createTask: (projectId: string, prompt: string) => request<Task>(`/projects/${projectId}/tasks`, { method: "POST", body: JSON.stringify({ prompt }) }),
  createIssueTask: (projectId: string, issue_number: number) => request<Task>(`/projects/${projectId}/issue-tasks`, { method: "POST", body: JSON.stringify({ issue_number }) }),
  createDiscoveryTask: (projectId: string, prompt?: string) => request<Task>(`/projects/${projectId}/discovery-tasks`, { method: "POST", body: JSON.stringify({ prompt: prompt || null }) }),
  discovery: (taskId: string) => request<DiscoverySummary>(`/tasks/${taskId}/discovery`),
  handoffTasks: (taskId: string) => request<Task[]>(`/tasks/${taskId}/handoff-tasks`),
  projectConfig: (projectId: string) => request<ProjectConfig>(`/projects/${projectId}/config`),
  updateProjectConfig: (projectId: string, patch: ProjectConfigPatch) =>
    request<ProjectConfig>(`/projects/${projectId}/config`, { method: "PATCH", body: JSON.stringify(patch) }),
  systemHealth: () => request<SystemHealth>("/system/health"),
  settings: () => request<Record<string, unknown>>("/settings"),
};

export function streamUrl(taskId: string): string {
  return `${API}/tasks/${taskId}/stream`;
}

export function loginUrl(): string {
  return `${API}/auth/github/login`;
}
