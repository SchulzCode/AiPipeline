import { describe, expect, it } from "vitest";
import { activityTone, discoveryTone, needsAttention, projectTone, taskStatusLabel, taskTone } from "./status";

describe("taskTone", () => {
  it("maps every in-progress phase to the active tone", () => {
    for (const status of ["ROUTING", "PREPARING", "IMPLEMENTING", "VERIFYING", "REVIEWING", "PR_OPEN", "CI", "MERGING", "POST_MERGE", "CLAIMED"]) {
      expect(taskTone(status)).toBe("active");
    }
  });

  it("distinguishes queued, done, attention, and failed states", () => {
    expect(taskTone("QUEUED")).toBe("queued");
    expect(taskTone("DONE")).toBe("done");
    expect(taskTone("BLOCKED")).toBe("attention");
    expect(taskTone("NEEDS_INPUT")).toBe("attention");
    expect(taskTone("FAILED")).toBe("failed");
    expect(taskTone("CANCELLED")).toBe("idle");
  });

  it("falls back to active for an unrecognized status rather than throwing", () => {
    expect(taskTone("SOMETHING_NEW")).toBe("active");
  });
});

describe("taskStatusLabel", () => {
  it("produces a human-readable label for known statuses", () => {
    expect(taskStatusLabel("PR_OPEN")).toBe("PR open");
    expect(taskStatusLabel("CI")).toBe("CI running");
  });

  it("passes through unknown statuses verbatim", () => {
    expect(taskStatusLabel("MYSTERY")).toBe("MYSTERY");
  });
});

describe("projectTone", () => {
  it("maps BUSY to active and IDLE to idle", () => {
    expect(projectTone("BUSY")).toBe("active");
    expect(projectTone("IDLE")).toBe("idle");
  });
});

describe("activityTone", () => {
  it("maps activity feed statuses to the shared tone set", () => {
    expect(activityTone("info")).toBe("active");
    expect(activityTone("success")).toBe("done");
    expect(activityTone("warning")).toBe("attention");
    expect(activityTone("error")).toBe("failed");
  });
});

describe("discoveryTone", () => {
  it("maps discovery candidate statuses", () => {
    expect(discoveryTone("proposed")).toBe("queued");
    expect(discoveryTone("created")).toBe("done");
    expect(discoveryTone("duplicate")).toBe("idle");
    expect(discoveryTone("failed")).toBe("failed");
  });
});

describe("needsAttention", () => {
  it("is true only for blocked, needs-input, and failed tasks", () => {
    expect(needsAttention("BLOCKED")).toBe(true);
    expect(needsAttention("NEEDS_INPUT")).toBe(true);
    expect(needsAttention("FAILED")).toBe(true);
    expect(needsAttention("DONE")).toBe(false);
    expect(needsAttention("IMPLEMENTING")).toBe(false);
    expect(needsAttention("CANCELLED")).toBe(false);
  });
});
