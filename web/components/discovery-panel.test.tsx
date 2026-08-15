import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { DiscoverySummary } from "@/lib/types";

const { discoveryMock, handoffTasksMock } = vi.hoisted(() => ({
  discoveryMock: vi.fn(),
  handoffTasksMock: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: { discovery: discoveryMock, handoffTasks: handoffTasksMock } }));

import { DiscoveryPanel } from "./discovery-panel";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DiscoveryPanel", () => {
  it("shows a pending state while discovery is still running", async () => {
    discoveryMock.mockResolvedValue({ status: "pending", candidates: [], created: [], duplicates: [], failed: [], handoff_issue_numbers: [] } satisfies DiscoverySummary);
    handoffTasksMock.mockResolvedValue([]);

    render(<DiscoveryPanel taskId="task-1" />);

    await waitFor(() => expect(screen.getByText("Discovering")).toBeInTheDocument());
  });

  it("renders ranked candidates and summary counts once results are ready", async () => {
    discoveryMock.mockResolvedValue({
      status: "ready",
      candidates: [
        {
          key: "cand-1",
          title: "Add dark mode",
          summary: "Add a dark theme toggle.",
          acceptance_criteria: [],
          task_type: "FEATURE",
          risk: "LOW",
          context_class: "NORMAL",
          labels: [],
          score: 0.82,
          rank: 1,
          status: "created",
          issue_number: 42,
          issue_url: "https://github.com/octo/demo/issues/42",
          handoff: true,
        },
      ],
      created: ["cand-1"],
      duplicates: [],
      failed: [],
      handoff_issue_numbers: [42],
    } satisfies DiscoverySummary);
    handoffTasksMock.mockResolvedValue([]);

    render(<DiscoveryPanel taskId="task-1" />);

    await waitFor(() => expect(screen.getByText("Add dark mode")).toBeInTheDocument());
    expect(screen.getByText("1 created")).toBeInTheDocument();
    expect(screen.getByText("Handed off for implementation")).toBeInTheDocument();
    expect(screen.getByText("Issue #42")).toBeInTheDocument();
  });

  it("shows an empty state when no candidates were proposed", async () => {
    discoveryMock.mockResolvedValue({ status: "ready", candidates: [], created: [], duplicates: [], failed: [], handoff_issue_numbers: [] } satisfies DiscoverySummary);
    handoffTasksMock.mockResolvedValue([]);

    render(<DiscoveryPanel taskId="task-1" />);

    await waitFor(() => expect(screen.getByText("No candidates were proposed")).toBeInTheDocument());
  });

  it("shows an error banner if the discovery request fails", async () => {
    discoveryMock.mockRejectedValue(new Error("discovery unavailable"));
    handoffTasksMock.mockResolvedValue([]);

    render(<DiscoveryPanel taskId="task-1" />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("discovery unavailable"));
  });
});
