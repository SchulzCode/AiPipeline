import type { ActivityFeed, AgentModels, Event, Installation, Issue, Project, Repository, Task, User } from "./types";

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

export const api = {
  me: () => request<User>("/auth/me"),
  projects: () => request<Project[]>("/projects"),
  project: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (data: object) => request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  agentModels: () => request<AgentModels>("/agents/models"),
  installations: () => request<Installation[]>("/github/installations"),
  installationRepos: (id: number) => request<Repository[]>(`/github/installations/${id}/repositories`),
  tasks: (projectId: string) => request<Task[]>(`/projects/${projectId}/tasks`),
  task: (id: string) => request<Task>(`/tasks/${id}`),
  events: (id: string) => request<Event[]>(`/tasks/${id}/events`),
  activity: (id: string) => request<ActivityFeed>(`/tasks/${id}/activity`),
  issues: (projectId: string) => request<Issue[]>(`/projects/${projectId}/issues`),
  createTask: (projectId: string, prompt: string) => request<Task>(`/projects/${projectId}/tasks`, { method: "POST", body: JSON.stringify({ prompt }) }),
  createIssueTask: (projectId: string, issue_number: number) => request<Task>(`/projects/${projectId}/issue-tasks`, { method: "POST", body: JSON.stringify({ issue_number }) }),
};
