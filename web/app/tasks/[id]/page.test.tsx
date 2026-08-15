import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ActivityFeed, Project, Task } from "@/lib/types";

const { apiMocks } = vi.hoisted(() => ({
  apiMocks: {
    task: vi.fn(),
    project: vi.fn(),
    events: vi.fn(),
    activity: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({
  api: apiMocks,
  streamUrl: (id: string) => `http://localhost:8000/tasks/${id}/stream`,
}));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "task-1" }) }));

// jsdom has no native EventSource. A minimal controllable stub is enough for
// these tests: the page only calls addEventListener("task", ...), .close(),
// and reads .onerror.
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (event: MessageEvent) => void) {
    this.listeners[type] = [...(this.listeners[type] ?? []), cb];
  }
  emit(type: string, data: unknown) {
    for (const cb of this.listeners[type] ?? []) cb({ data: JSON.stringify(data) } as MessageEvent);
  }
  close() {
    this.closed = true;
  }
}

vi.stubGlobal("EventSource", FakeEventSource);

import TaskPage from "./page";

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
  status: "BUSY",
  created_at: "2026-08-15T10:00:00Z",
};

function makeTask(overrides: Partial<Task>): Task {
  return {
    id: "task-1",
    project_id: "proj-1",
    source: "prompt",
    source_reference: null,
    title: "Add rate limiting",
    prompt: "Add rate limiting",
    status: "IMPLEMENTING",
    risk: "MEDIUM",
    context_class: "DEEP",
    core_task_id: null,
    discovery_task_id: null,
    branch: "aipipe/task-1",
    pr_number: null,
    error: null,
    failure_category: null,
    worker_build: null,
    input_tokens: 1000,
    output_tokens: 500,
    created_at: "2026-08-15T09:00:00Z",
    started_at: "2026-08-15T09:01:00Z",
    completed_at: null,
    ...overrides,
  };
}

function emptyFeed(overrides: Partial<ActivityFeed> = {}): ActivityFeed {
  return { items: [], current: null, blocker: null, checks: { checks: [] }, ...overrides };
}

beforeEach(() => {
  FakeEventSource.instances = [];
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Task detail page", () => {
  it("renders task identity, agent, and pipeline once loaded", async () => {
    apiMocks.task.mockResolvedValue(makeTask({}));
    apiMocks.project.mockResolvedValue(PROJECT);
    apiMocks.events.mockResolvedValue([]);
    apiMocks.activity.mockResolvedValue(emptyFeed());

    render(<TaskPage />);

    await waitFor(() => expect(screen.getByText("Add rate limiting")).toBeInTheDocument());
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Pipeline" })).toBeInTheDocument();
  });

  it("renders a blocker banner with the failure category for a blocked task", async () => {
    apiMocks.task.mockResolvedValue(makeTask({ status: "BLOCKED", failure_category: "QUALITY_GATE" }));
    apiMocks.project.mockResolvedValue(PROJECT);
    apiMocks.events.mockResolvedValue([]);
    apiMocks.activity.mockResolvedValue(
      emptyFeed({ blocker: { reason: "Lint failed after 3 attempts.", last_phase: "Verifying", category: "QUALITY_GATE" } })
    );

    render(<TaskPage />);

    await waitFor(() => expect(screen.getByText(/Task blocked/)).toBeInTheDocument());
    expect(screen.getByText(/QUALITY_GATE/)).toBeInTheDocument();
    expect(screen.getByText("Lint failed after 3 attempts.")).toBeInTheDocument();
  });

  it("applies a live SSE task event by re-fetching activity", async () => {
    apiMocks.task.mockResolvedValue(makeTask({}));
    apiMocks.project.mockResolvedValue(PROJECT);
    apiMocks.events.mockResolvedValue([]);
    apiMocks.activity.mockResolvedValue(emptyFeed());

    render(<TaskPage />);

    await waitFor(() => expect(screen.getByText("Add rate limiting")).toBeInTheDocument());
    expect(FakeEventSource.instances).toHaveLength(1);

    apiMocks.activity.mockResolvedValueOnce(
      emptyFeed({ current: { title: "Running verification", summary: "", phase: "VERIFYING", started_at: "2026-08-15T09:05:00Z", agent_label: "Codex" } })
    );
    FakeEventSource.instances[0].emit("task", { id: 1, task_id: "task-1", kind: "core:event", detail: "{}", created_at: "2026-08-15T09:05:00Z" });

    await waitFor(() => expect(screen.getByText("Running verification")).toBeInTheDocument());
  });

  it("toggles the technical details panel to reveal raw events", async () => {
    apiMocks.task.mockResolvedValue(makeTask({}));
    apiMocks.project.mockResolvedValue(PROJECT);
    apiMocks.events.mockResolvedValue([{ id: 1, task_id: "task-1", kind: "core:status", detail: "{\"status\":\"IMPLEMENTING\"}", created_at: "2026-08-15T09:01:00Z" }]);
    apiMocks.activity.mockResolvedValue(emptyFeed());

    render(<TaskPage />);

    await waitFor(() => expect(screen.getByText(/Technical details/)).toBeInTheDocument());
    expect(screen.queryByText("core:status")).not.toBeInTheDocument();

    await userEvent.click(screen.getByText(/Technical details/));
    expect(screen.getByText("core:status")).toBeInTheDocument();
  });

  it("shows an error banner when the task cannot be loaded", async () => {
    apiMocks.task.mockRejectedValue(new Error("Task not found"));
    apiMocks.events.mockResolvedValue([]);
    apiMocks.activity.mockResolvedValue(emptyFeed());

    render(<TaskPage />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Task not found"));
  });
});
