import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { AgentModels, Project, ProjectConfig } from "@/lib/types";

const { apiMocks } = vi.hoisted(() => ({
  apiMocks: {
    project: vi.fn(),
    projectConfig: vi.fn(),
    updateProjectConfig: vi.fn(),
    updateProject: vi.fn(),
    agentModels: vi.fn(),
  },
}));

vi.mock("@/lib/api", () => ({ api: apiMocks }));
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "proj-1" }) }));

import ProjectSettingsPage from "./page";

const PROJECT: Project = {
  id: "proj-1",
  name: "Demo App",
  repository_full_name: null,
  repository_url: null,
  local_path: "/workspace/demo",
  installation_id: null,
  default_branch: "main",
  agent: "codex",
  model: null,
  enabled: true,
  status: "IDLE",
  created_at: "2026-08-15T10:00:00Z",
};

const CONFIG: ProjectConfig = {
  source: "local",
  editable: true,
  warning: null,
  config: {
    main_branch: "main",
    agent: "codex",
    auto_merge: true,
    merge_method: "squash",
    ci_timeout_seconds: 1800,
    ci_registration_grace_seconds: 90,
    command_timeout_seconds: 1200,
    implementation_attempts: 3,
    verification_attempts: 3,
    review_attempts: 2,
    ci_attempts: 2,
    external_attempts: 3,
    external_backoff_seconds: 2,
    planner_attempts: 2,
    planner_enabled: true,
    planner_context_classes: ["DEEP"],
    setup_commands: {},
    setup_auto: true,
    quality_commands: {},
    security_commands: {},
    discovery_max_candidates: 5,
    discovery_max_new_issues: 5,
    discovery_max_auto_implement: 0,
    discovery_max_risk: "MEDIUM",
    discovery_max_context_class: "NORMAL",
    discovery_attempts: 2,
  },
};

const AGENT_MODELS: AgentModels = {
  codex: [{ id: null, label: "Default (automatic)" }, { id: "gpt-5-codex", label: "GPT-5 Codex" }],
  claude: [{ id: null, label: "Default (automatic)" }, { id: "sonnet", label: "Sonnet" }],
  qwen: [{ id: null, label: "Default (automatic)" }, { id: "qwen-local", label: "Local Qwen (qwen-local)" }],
};

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function setupDefaults() {
  apiMocks.project.mockResolvedValue(PROJECT);
  apiMocks.projectConfig.mockResolvedValue(CONFIG);
  apiMocks.agentModels.mockResolvedValue(AGENT_MODELS);
}

describe("Project settings page", () => {
  it("loads and displays the current pipeline configuration", async () => {
    setupDefaults();
    render(<ProjectSettingsPage />);

    await waitFor(() => expect(screen.getByDisplayValue("main")).toBeInTheDocument());
    expect(screen.getByDisplayValue("1800")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Auto-merge/ })).toBeChecked();
    // Save is disabled until something changes.
    expect(screen.getByRole("button", { name: /Save changes/ })).toBeDisabled();
  });

  it("enables Save once a field changes, and persists only the changed fields", async () => {
    setupDefaults();
    apiMocks.updateProjectConfig.mockResolvedValue({ ...CONFIG, config: { ...CONFIG.config, ci_attempts: 5 } });
    render(<ProjectSettingsPage />);

    await waitFor(() => expect(screen.getByDisplayValue("main")).toBeInTheDocument());

    const ciAttempts = screen.getByLabelText("CI attempts");
    await userEvent.clear(ciAttempts);
    await userEvent.type(ciAttempts, "5");
    await userEvent.tab(); // blur to commit the clamped value

    const saveButton = screen.getByRole("button", { name: /Save changes/ });
    expect(saveButton).toBeEnabled();
    await userEvent.click(saveButton);

    await waitFor(() => expect(apiMocks.updateProjectConfig).toHaveBeenCalledWith("proj-1", { ci_attempts: 5 }));
    await waitFor(() => expect(screen.getByText("Saved.")).toBeInTheDocument());
  });

  it("can select and persist Local Qwen with the configured model", async () => {
    setupDefaults();
    apiMocks.updateProject.mockResolvedValue({ ...PROJECT, agent: "qwen", model: "qwen-local" });
    render(<ProjectSettingsPage />);

    await waitFor(() => expect(screen.getByLabelText("Agent")).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("Agent"), "qwen");
    expect(screen.getByText(/requires a compatible OpenAI-style model server/i)).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Model"), "qwen-local");
    await userEvent.click(screen.getByRole("button", { name: /Save changes/ }));

    await waitFor(() => expect(apiMocks.updateProject).toHaveBeenCalledWith("proj-1", { agent: "qwen", model: "qwen-local" }));
    await waitFor(() => expect(screen.getByText("Saved.")).toBeInTheDocument());
  });

  it("reloads an existing Local Qwen project with its model selected", async () => {
    apiMocks.project.mockResolvedValue({ ...PROJECT, agent: "qwen", model: "qwen-local" });
    apiMocks.projectConfig.mockResolvedValue({ ...CONFIG, config: { ...CONFIG.config, agent: "qwen" } });
    apiMocks.agentModels.mockResolvedValue(AGENT_MODELS);
    render(<ProjectSettingsPage />);

    await waitFor(() => expect(screen.getByLabelText("Agent")).toHaveValue("qwen"));
    expect(screen.getByLabelText("Model")).toHaveValue("qwen-local");
    expect(screen.getByText(/requires a compatible OpenAI-style model server/i)).toBeInTheDocument();
  });

  it("clamps numeric input to the field's allowed range on blur", async () => {
    setupDefaults();
    render(<ProjectSettingsPage />);

    await waitFor(() => expect(screen.getByDisplayValue("main")).toBeInTheDocument());
    const ciAttempts = screen.getByLabelText("CI attempts") as HTMLInputElement;
    await userEvent.clear(ciAttempts);
    await userEvent.type(ciAttempts, "99");
    await userEvent.tab();

    expect(ciAttempts.value).toBe("10"); // max is 10
  });

  it("disables all fields when the project config is not editable", async () => {
    apiMocks.project.mockResolvedValue({ ...PROJECT, local_path: null });
    apiMocks.projectConfig.mockResolvedValue({ ...CONFIG, source: "unavailable", editable: false, warning: "No local path or GitHub repository." });
    apiMocks.agentModels.mockResolvedValue(AGENT_MODELS);
    render(<ProjectSettingsPage />);

    await waitFor(() => expect(screen.getByText(/cannot be edited/)).toBeInTheDocument());
    expect(screen.getByLabelText("CI attempts")).toBeDisabled();
    expect(screen.getByRole("button", { name: /Save changes/ })).toBeDisabled();
  });
});
