import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const { apiMocks, routerPush } = vi.hoisted(() => ({
  apiMocks: {
    agentModels: vi.fn(),
    installations: vi.fn(),
    installationRepos: vi.fn(),
    createProject: vi.fn(),
  },
  routerPush: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: routerPush }) }));

import NewProject from "./page";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Add project page", () => {
  it("creates a Local Qwen project with the configured model", async () => {
    apiMocks.agentModels.mockResolvedValue({
      codex: [{ id: null, label: "Default (automatic)" }],
      claude: [{ id: null, label: "Default (automatic)" }],
      qwen: [
        { id: null, label: "Default (automatic)" },
        { id: "qwen-local", label: "Local Qwen (qwen-local)" },
      ],
    });
    apiMocks.installations.mockResolvedValue([]);
    apiMocks.createProject.mockResolvedValue({ id: "proj-local" });

    render(<NewProject />);
    await waitFor(() => expect(screen.getByLabelText("Agent")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Local server path" }));
    await userEvent.type(screen.getByLabelText("Local path on the AIpipe server"), "/workspace/demo");
    await userEvent.type(screen.getByLabelText("Display name"), "Local Demo");
    await userEvent.selectOptions(screen.getByLabelText("Agent"), "qwen");
    expect(screen.getByText(/requires a compatible OpenAI-style model server/i)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Model"), "qwen-local");
    await userEvent.click(screen.getByRole("button", { name: "Create project" }));

    await waitFor(() =>
      expect(apiMocks.createProject).toHaveBeenCalledWith({
        name: "Local Demo",
        agent: "qwen",
        model: "qwen-local",
        local_path: "/workspace/demo",
      }),
    );
    expect(routerPush).toHaveBeenCalledWith("/projects/proj-local");
  });
});
