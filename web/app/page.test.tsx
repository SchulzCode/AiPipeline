import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Project, TaskWithProject } from "@/lib/types";

const { projectsMock, allTasksMock } = vi.hoisted(() => ({
  projectsMock: vi.fn(),
  allTasksMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  api: { projects: projectsMock, allTasks: allTasksMock },
}));

import Overview from "./page";

const PROJECT_A: Project = {
  id: "p-active",
  name: "Alpha",
  repository_full_name: "octo/alpha",
  repository_url: null,
  local_path: null,
  installation_id: null,
  default_branch: "main",
  agent: "codex",
  model: null,
  enabled: true,
  status: "BUSY",
  created_at: "2026-08-15T10:00:00Z",
};

const PROJECT_B: Project = {
  id: "p-idle",
  name: "Beta",
  repository_full_name: "octo/beta",
  repository_url: null,
  local_path: null,
  installation_id: null,
  default_branch: "main",
  agent: "claude",
  model: "sonnet",
  enabled: true,
  status: "IDLE",
  created_at: "2026-08-14T10:00:00Z",
};

function task(overrides: Partial<TaskWithProject>): TaskWithProject {
  return {
    id: "t-1",
    project_id: "p-active",
    project_name: "Alpha",
    project_agent: "codex",
    project_model: null,
    source: "prompt",
    source_reference: null,
    title: "Add rate limiting",
    prompt: "Add rate limiting",
    status: "IMPLEMENTING",
    risk: "MEDIUM",
    context_class: "DEEP",
    core_task_id: null,
    discovery_task_id: null,
    branch: null,
    pr_number: null,
    error: null,
    failure_category: null,
    worker_build: null,
    input_tokens: 100,
    output_tokens: 50,
    created_at: "2026-08-15T11:00:00Z",
    started_at: "2026-08-15T11:00:00Z",
    completed_at: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Overview page", () => {
  it("shows a loading skeleton before data arrives", async () => {
    let resolveProjects: (v: Project[]) => void = () => {};
    projectsMock.mockReturnValue(new Promise((r) => (resolveProjects = r)));
    allTasksMock.mockResolvedValue([]);

    render(<Overview />);
    expect(screen.getByText(/Overview/i)).toBeInTheDocument();
    // Stat tiles render skeletons (no numeric value) while tasks is still null.
    expect(screen.queryByText("Nothing running right now")).not.toBeInTheDocument();

    resolveProjects([]);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());
  });

  it("renders an empty state when there are no projects", async () => {
    projectsMock.mockResolvedValue([]);
    allTasksMock.mockResolvedValue([]);
    render(<Overview />);
    await waitFor(() => expect(screen.getByText("No projects yet")).toBeInTheDocument());
    expect(screen.getByText("Add your first project →")).toBeInTheDocument();
  });

  it("surfaces active tasks under Happening now and attention-needed tasks separately", async () => {
    projectsMock.mockResolvedValue([PROJECT_A, PROJECT_B]);
    allTasksMock.mockResolvedValue([
      task({ id: "t-active", status: "IMPLEMENTING" }),
      task({ id: "t-blocked", status: "BLOCKED", title: "Needs a decision", project_id: "p-idle", project_name: "Beta" }),
    ]);

    render(<Overview />);

    await waitFor(() => expect(screen.getByText("Needs a decision")).toBeInTheDocument());

    const attentionSection = screen.getByRole("heading", { name: /Needs attention/ }).closest("section")!;
    expect(within(attentionSection).getByText("Needs a decision")).toBeInTheDocument();

    const happeningSection = screen.getByRole("heading", { name: "Happening now" }).closest("section")!;
    expect(within(happeningSection).getByText("Add rate limiting")).toBeInTheDocument();

    // Both project cards render with their differentiated status badges.
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Beta")).toBeInTheDocument();
  });

  it("filters the project grid by search text", async () => {
    projectsMock.mockResolvedValue([PROJECT_A, PROJECT_B]);
    allTasksMock.mockResolvedValue([]);
    render(<Overview />);

    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Search projects…"), "Alpha");

    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Beta")).not.toBeInTheDocument();
  });

  it("shows an error banner when the projects request fails", async () => {
    projectsMock.mockRejectedValue(new Error("network down"));
    allTasksMock.mockResolvedValue([]);
    render(<Overview />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("network down"));
  });
});
