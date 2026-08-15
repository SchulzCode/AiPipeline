import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { TaskWithProject } from "@/lib/types";

const { allTasksMock } = vi.hoisted(() => ({ allTasksMock: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { allTasks: allTasksMock } }));

import GlobalTasksPage from "./page";

function task(overrides: Partial<TaskWithProject>): TaskWithProject {
  return {
    id: "t-1",
    project_id: "p-1",
    project_name: "Alpha",
    project_agent: "codex",
    project_model: null,
    source: "prompt",
    source_reference: null,
    title: "Task title",
    prompt: "Task title",
    status: "QUEUED",
    risk: null,
    context_class: null,
    core_task_id: null,
    discovery_task_id: null,
    branch: null,
    pr_number: null,
    error: null,
    failure_category: null,
    worker_build: null,
    input_tokens: 0,
    output_tokens: 0,
    created_at: "2026-08-15T10:00:00Z",
    started_at: null,
    completed_at: null,
    ...overrides,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Global tasks page", () => {
  it("shows an empty state when nothing matches", async () => {
    allTasksMock.mockResolvedValue([]);
    render(<GlobalTasksPage />);
    await waitFor(() => expect(screen.getByText("No matching tasks")).toBeInTheDocument());
  });

  it("filters tasks by status group", async () => {
    allTasksMock.mockResolvedValue([
      task({ id: "t-queued", status: "QUEUED", title: "Queued task" }),
      task({ id: "t-done", status: "DONE", title: "Done task" }),
    ]);
    render(<GlobalTasksPage />);

    await waitFor(() => expect(screen.getByText("Queued task")).toBeInTheDocument());
    expect(screen.getByText("Done task")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /^Done/ }));
    expect(screen.getByText("Done task")).toBeInTheDocument();
    expect(screen.queryByText("Queued task")).not.toBeInTheDocument();
  });

  it("filters tasks by search text across title and project name", async () => {
    allTasksMock.mockResolvedValue([
      task({ id: "t-1", title: "Add rate limiting", project_name: "Alpha" }),
      task({ id: "t-2", title: "Fix flaky test", project_name: "Beta" }),
    ]);
    render(<GlobalTasksPage />);

    await waitFor(() => expect(screen.getByText("Add rate limiting")).toBeInTheDocument());
    await userEvent.type(screen.getByPlaceholderText("Search tasks or projects…"), "Beta");

    expect(screen.getByText("Fix flaky test")).toBeInTheDocument();
    expect(screen.queryByText("Add rate limiting")).not.toBeInTheDocument();
  });

  it("shows an error banner when the request fails", async () => {
    allTasksMock.mockRejectedValue(new Error("boom"));
    render(<GlobalTasksPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("boom"));
  });
});
