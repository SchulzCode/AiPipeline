"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import type { AgentModels, Installation, Repository } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { ErrorBanner } from "@/components/ui/error-banner";

const FIELD = "mt-2 w-full rounded-md border border-border bg-surface-sunken px-3 py-2.5 text-sm text-fg focus-visible:border-accent";
const LABEL = "block text-sm font-medium text-fg";

export default function NewProject() {
  const router = useRouter();

  const [mode, setMode] = useState<"github" | "local">("github");
  const [name, setName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [agent, setAgent] = useState("codex");
  const [agentModels, setAgentModels] = useState<AgentModels>({});
  const [model, setModel] = useState("");

  const [installations, setInstallations] = useState<Installation[]>([]);
  const [installation, setInstallation] = useState("");
  const [repos, setRepos] = useState<Repository[]>([]);
  const [repo, setRepo] = useState("");

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.agentModels()
      .then((items) => {
        if (!cancelled) setAgentModels(items);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (mode !== "github") return;
    let cancelled = false;
    api.installations()
      .then((items) => {
        if (cancelled) return;
        setInstallations(items);
        if (items.length === 1) setInstallation(String(items[0].id));
      })
      .catch((e) => {
        if (!cancelled) setError(`GitHub App: ${String(e)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [mode]);

  useEffect(() => {
    const id = Number(installation);
    if (!id) return;
    let cancelled = false;
    api.installationRepos(id)
      .then((items) => {
        if (!cancelled) setRepos(items);
      })
      .catch((e) => {
        if (!cancelled) setError(`Repositories: ${String(e)}`);
      });
    return () => {
      cancelled = true;
    };
  }, [installation]);

  function handleInstallationChange(value: string) {
    setInstallation(value);
    setRepos([]);
    setRepo("");
    setError("");
  }

  function handleAgentChange(value: string) {
    setAgent(value);
    setModel("");
  }

  function handleRepositoryChange(value: string) {
    setRepo(value);
    if (!name) setName(value.split("/").pop() || "");
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const selected = repos.find((item) => item.full_name === repo);
      const project = await api.createProject({
        name: name || selected?.name || repo.split("/").pop() || "Project",
        agent,
        model: model || null,
        ...(mode === "github"
          ? { repository_full_name: repo, installation_id: Number(installation), default_branch: selected?.default_branch || "main" }
          : { local_path: localPath }),
      });
      router.push(`/projects/${project.id}`);
    } catch (e) {
      setError(String(e));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-xl font-semibold tracking-tight text-fg">Add project</h1>
      <p className="mt-1 text-sm text-fg-muted">Register a repository. AIpipe keeps orchestration in the backend, not in the browser.</p>

      <form onSubmit={submit} className="mt-6 space-y-5 rounded-lg border border-border bg-surface p-6">
        <div className="flex rounded-md bg-surface-sunken p-1 text-sm">
          {(["github", "local"] as const).map((item) => (
            <button
              type="button"
              key={item}
              onClick={() => setMode(item)}
              className={`flex-1 rounded-sm px-3 py-2 transition-colors duration-150 ${mode === item ? "bg-accent-solid text-accent-fg" : "text-fg-muted hover:text-fg"}`}
            >
              {item === "github" ? "GitHub" : "Local server path"}
            </button>
          ))}
        </div>

        {mode === "github" ? (
          <>
            <label className={LABEL}>
              GitHub App installation
              <select required value={installation} onChange={(e) => handleInstallationChange(e.target.value)} className={FIELD}>
                <option value="">Select installation…</option>
                {installations.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.account} · {item.id}
                  </option>
                ))}
              </select>
            </label>

            <label className={LABEL}>
              Repository
              <select required value={repo} onChange={(e) => handleRepositoryChange(e.target.value)} className={FIELD}>
                <option value="">Select repository…</option>
                {repos.map((item) => (
                  <option key={item.id} value={item.full_name}>
                    {item.full_name}
                    {item.private ? " · private" : ""}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : (
          <label className={LABEL}>
            Local path on the AIpipe server
            <input required value={localPath} onChange={(e) => setLocalPath(e.target.value)} className={FIELD} placeholder="/workspace/my-project" />
          </label>
        )}

        <label className={LABEL}>
          Display name
          <input required value={name} onChange={(e) => setName(e.target.value)} className={FIELD} placeholder="Backend API" />
        </label>

        <label className={LABEL}>
          Agent
          <select value={agent} onChange={(e) => handleAgentChange(e.target.value)} className={FIELD}>
            <option value="codex">Codex</option>
            <option value="claude">Claude Code</option>
            <option value="qwen">Local Qwen</option>
          </select>
        </label>

        <label className={LABEL}>
          Model
          <select value={model} onChange={(e) => setModel(e.target.value)} className={FIELD}>
            {(agentModels[agent] || []).map((item) => (
              <option key={item.id ?? ""} value={item.id ?? ""}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        {agent === "qwen" ? (
          <p className="rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-fg-muted">
            Local Qwen requires a compatible OpenAI-style model server to be running separately and reachable by the AIpipe worker.
          </p>
        ) : null}

        {error ? <ErrorBanner message={error} /> : null}

        <Button type="submit" variant="primary" disabled={busy}>
          {busy ? "Adding…" : "Create project"}
        </Button>
      </form>
    </div>
  );
}
