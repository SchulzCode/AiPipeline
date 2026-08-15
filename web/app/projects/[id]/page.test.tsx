import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Issue, Project, Task } from "@/lib/types";

const { apiMocks, pushMock } = vi.hoisted(() => ({
  apiMocks: {
    project: vi.fn(),
    tasks: vi.fn(),
    issues: vi.fn(),
    createTask: vi.fn(),
    createIssueTask: vi.fn(),
    createDiscoveryTask: vi.fn(),
  },
  pushMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "proj-1" }),
  useRouter: () => ({ push: pushMock }),
}));

import ProjectPage from "./page";

const PROJECT: Project = {
  id: "proj-1",
  name: "Demo App",
  repository_full_name: "octo/demo",
  repository_url: null,
  local_path: null,
  installation_id: 1,
  default_branch: "main",
  agent: "codex",
  model: null,
  enabled: true,
  status: "IDLE",
  created_at: "2026-08-15T10:00:00Z",
};

const TASKS: Task[] = [
  {
    id: "task-1",
    project_id: "proj-1",
    source: "prompt",
    source_reference: null,
    title: "Add caching layer",
    prompt: "Add caching layer",
    status: "DONE",
    risk: "LOW",
    context_class: "NORMAL",
    core_task_id: null,
    discovery_task_id: null,
    branch: null,
    pr_number: null,
    error: null,
    failure_category: null,
    worker_build: null,
    input_tokens: 10,
    output_tokens: 5,
    created_at: "2026-08-15T09:00:00Z",
    started_at: null,
    completed_at: "2026-08-15T09:30:00Z",
  },
];

const ISSUES: Issue[] = [{ number: 42, title: "Flaky test in CI", state: "open", url: "https://github.com/octo/demo/issues/42", labels: [] }];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function setupDefaults() {
  apiMocks.project.mockResolvedValue(PROJECT);
  apiMocks.tasks.mockResolvedValue(TASKS);
  apiMocks.issues.mockResolvedValue(ISSUES);
}

describe("Project workspace page", () => {
  it("renders project identity, tasks, and open issues once loaded", async () => {
    setupDefaults();
    render(<ProjectPage />);

    await waitFor(() => expect(screen.getByText("Demo App")).toBeInTheDocument());
    expect(screen.getByText("Add caching layer")).toBeInTheDocument();
    expect(screen.getByText("Flaky test in CI")).toBeInTheDocument();
  });

  it("submits a new prompt task and navigates to its detail page", async () => {
    setupDefaults();
    apiMocks.createTask.mockResolvedValue({ id: "task-new" });
    render(<ProjectPage />);

    await waitFor(() => expect(screen.getByText("Demo App")).toBeInTheDocument());

    const textarea = screen.getByPlaceholderText(/Add rate limiting/);
    await userEvent.type(textarea, "Add a health check endpoint");
    await userEvent.click(screen.getByRole("button", { name: /Run task/ }));

    await waitFor(() => expect(apiMocks.createTask).toHaveBeenCalledWith("proj-1", "Add a health check endpoint"));
    expect(pushMock).toHaveBeenCalledWith("/tasks/task-new");
  });

  it("runs a GitHub issue with AIpipe and navigates to the new task", async () => {
    setupDefaults();
    apiMocks.createIssueTask.mockResolvedValue({ id: "task-from-issue" });
    render(<ProjectPage />);

    await waitFor(() => expect(screen.getByText("Flaky test in CI")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Run with AIpipe" }));

    await waitFor(() => expect(apiMocks.createIssueTask).toHaveBeenCalledWith("proj-1", 42));
    expect(pushMock).toHaveBeenCalledWith("/tasks/task-from-issue");
  });

  it("launches feature discovery for GitHub-backed projects", async () => {
    setupDefaults();
    apiMocks.createDiscoveryTask.mockResolvedValue({ id: "task-discovery" });
    render(<ProjectPage />);

    await waitFor(() => expect(screen.getByText("Feature discovery")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: "Discover features" }));

    await waitFor(() => expect(apiMocks.createDiscoveryTask).toHaveBeenCalledWith("proj-1"));
    expect(pushMock).toHaveBeenCalledWith("/tasks/task-discovery");
  });

  it("filters the task list by status", async () => {
    setupDefaults();
    apiMocks.tasks.mockResolvedValue([
      ...TASKS,
      { ...TASKS[0], id: "task-2", title: "In progress work", status: "IMPLEMENTING" },
    ]);
    render(<ProjectPage />);

    await waitFor(() => expect(screen.getByText("Add caching layer")).toBeInTheDocument());
    const taskList = screen.getByRole("heading", { name: "Tasks" }).closest("section")!;
    expect(within(taskList).getByText("In progress work")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Done" }));
    expect(within(taskList).getByText("Add caching layer")).toBeInTheDocument();
    expect(within(taskList).queryByText("In progress work")).not.toBeInTheDocument();
  });

  it("shows an empty state when there are no tasks yet", async () => {
    apiMocks.project.mockResolvedValue(PROJECT);
    apiMocks.tasks.mockResolvedValue([]);
    apiMocks.issues.mockResolvedValue([]);
    render(<ProjectPage />);

    await waitFor(() => expect(screen.getByText("No tasks yet")).toBeInTheDocument());
  });
});
