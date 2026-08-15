import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { PipelineStages } from "./pipeline-stages";
import type { ActivityFeed } from "@/lib/types";

function feedWithCategories(categories: string[]): ActivityFeed {
  return {
    items: categories.map((category, i) => ({
      category,
      title: category,
      summary: "",
      status: "info",
      timestamp: new Date(i * 1000).toISOString(),
    })),
    current: null,
    blocker: null,
    checks: { checks: [] },
  };
}

describe("PipelineStages", () => {
  it("marks earlier stages done, the current stage active, and later stages pending", () => {
    const activity = feedWithCategories(["ROUTING", "PREPARING", "DISCOVERY", "PLANNING", "IMPLEMENTING"]);
    render(<PipelineStages activity={activity} taskStatus="IMPLEMENTING" />);

    expect(screen.getByText("Routing").closest("li")).not.toHaveAttribute("aria-current");
    expect(screen.getByText("Implementing").closest("li")).toHaveAttribute("aria-current", "step");
    // Stages after the current one should not be marked done or active.
    expect(screen.getByText("Reviewing").closest("li")).not.toHaveAttribute("aria-current");
  });

  it("marks a phase skipped when it never appeared in the activity feed but a later phase did", () => {
    // PLANNING never ran (e.g. a shallow-context task), but IMPLEMENTING did.
    const activity = feedWithCategories(["ROUTING", "PREPARING", "IMPLEMENTING"]);
    render(<PipelineStages activity={activity} taskStatus="IMPLEMENTING" />);

    const planning = screen.getByText("Planning").closest("li");
    expect(planning?.textContent).toContain("Planning");
    // Skipped stages render with the muted/pending styling, not the done (emerald) styling.
    expect(planning?.className).not.toContain("status-done");
  });

  it("marks the current stage as failed when the task stopped in a terminal-bad state", () => {
    const activity = feedWithCategories(["ROUTING", "PREPARING", "IMPLEMENTING"]);
    render(<PipelineStages activity={activity} taskStatus="BLOCKED" />);

    const implementing = screen.getByText("Implementing").closest("li");
    expect(implementing?.className).toContain("status-failed");
  });

  it("marks every stage done when the task is DONE", () => {
    const activity = feedWithCategories(["ROUTING", "PREPARING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "PR_OPEN", "CI", "MERGING", "POST_MERGE", "DONE"]);
    render(<PipelineStages activity={activity} taskStatus="DONE" />);

    const done = screen.getByText("Done").closest("li");
    expect(done?.className).toContain("status-done");
  });

  it("renders all twelve stages", () => {
    render(<PipelineStages activity={null} taskStatus="QUEUED" />);
    expect(screen.getAllByRole("listitem")).toHaveLength(12);
  });
});
