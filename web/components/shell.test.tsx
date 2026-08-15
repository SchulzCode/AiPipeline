import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { User } from "@/lib/types";

const { meMock } = vi.hoisted(() => ({ meMock: vi.fn() }));

vi.mock("@/lib/api", () => ({ api: { me: meMock }, loginUrl: () => "http://localhost:8000/auth/github/login" }));
vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

import { Shell } from "./shell";

const USER: User = { id: "u1", login: "octocat", avatar_url: null };

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Shell", () => {
  it("shows a loading state before the auth check resolves", () => {
    meMock.mockReturnValue(new Promise(() => {}));
    render(
      <Shell>
        <div>content</div>
      </Shell>
    );
    expect(screen.getByText(/Loading AIpipe/)).toBeInTheDocument();
  });

  it("shows a sign-in card when signed out", async () => {
    meMock.mockRejectedValue(new Error("401"));
    render(
      <Shell>
        <div>content</div>
      </Shell>
    );
    await waitFor(() => expect(screen.getByRole("link", { name: /Sign in with GitHub/ })).toBeInTheDocument());
    expect(screen.queryByText("content")).not.toBeInTheDocument();
  });

  it("renders navigation and children once signed in", async () => {
    meMock.mockResolvedValue(USER);
    render(
      <Shell>
        <div>content</div>
      </Shell>
    );
    await waitFor(() => expect(screen.getByText("content")).toBeInTheDocument());
    expect(screen.getByText("octocat")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Overview/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: /Tasks/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Diagnostics/ })).toBeInTheDocument();
  });

  it("collapses nav labels to icon-only below the md breakpoint", async () => {
    meMock.mockResolvedValue(USER);
    render(
      <Shell>
        <div>content</div>
      </Shell>
    );
    await waitFor(() => expect(screen.getByText("content")).toBeInTheDocument());
    const tasksLink = screen.getByRole("link", { name: /Tasks/ });
    const label = tasksLink.querySelector("span");
    expect(label).toHaveClass("hidden");
    expect(label).toHaveClass("md:inline");
  });

  it("has a skip-to-content link for keyboard users", async () => {
    meMock.mockResolvedValue(USER);
    render(
      <Shell>
        <div>content</div>
      </Shell>
    );
    await waitFor(() => expect(screen.getByText("content")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main-content");
  });
});
