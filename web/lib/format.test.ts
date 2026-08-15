import { describe, expect, it } from "vitest";
import { agentLabel, formatRelativeTime, formatTimestamp, formatTokenCount } from "./format";

describe("agentLabel", () => {
  it("labels a known agent without a model", () => {
    expect(agentLabel({ agent: "codex", model: null })).toBe("Codex");
  });

  it("appends the model when set", () => {
    expect(agentLabel({ agent: "claude", model: "sonnet" })).toBe("Claude · sonnet");
  });

  it("falls back to the raw agent string for unknown agents", () => {
    expect(agentLabel({ agent: "gemini", model: null })).toBe("gemini");
  });
});

describe("formatRelativeTime", () => {
  const now = new Date("2026-08-15T12:00:00Z").getTime();

  it("reports 'just now' for very recent timestamps", () => {
    expect(formatRelativeTime(new Date(now - 2000).toISOString(), now)).toBe("just now");
  });

  it("reports seconds, minutes, hours, and days scaled correctly", () => {
    expect(formatRelativeTime(new Date(now - 30_000).toISOString(), now)).toBe("30s ago");
    expect(formatRelativeTime(new Date(now - 5 * 60_000).toISOString(), now)).toBe("5m ago");
    expect(formatRelativeTime(new Date(now - 3 * 3600_000).toISOString(), now)).toBe("3h ago");
    expect(formatRelativeTime(new Date(now - 2 * 86400_000).toISOString(), now)).toBe("2d ago");
  });

  it("falls back to an absolute timestamp beyond a week", () => {
    const eightDaysAgo = new Date(now - 8 * 86400_000).toISOString();
    expect(formatRelativeTime(eightDaysAgo, now)).toBe(formatTimestamp(eightDaysAgo));
  });
});

describe("formatTokenCount", () => {
  it("shows raw numbers under 1000", () => {
    expect(formatTokenCount(842)).toBe("842");
  });

  it("compacts thousands with one decimal, trimming a trailing .0", () => {
    expect(formatTokenCount(12400)).toBe("12.4k");
    expect(formatTokenCount(5000)).toBe("5k");
  });

  it("compacts millions", () => {
    expect(formatTokenCount(2_500_000)).toBe("2.5M");
  });
});
