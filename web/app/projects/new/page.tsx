"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import type { Installation, Repository } from "@/lib/types";

export default function NewProject() {
  const router = useRouter();
  const [mode, setMode] = useState<"github" | "local">("github");
  const [name, setName] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [agent, setAgent] = useState("codex");
  const [installations, setInstallations] = useState<Installation[]>([]);
  const [installation, setInstallation] = useState("");
  const [repos, setRepos] = useState<Repository[]>([]);
  const [repo, setRepo] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (mode !== "github") return;
    api.installations().then((items) => {
      setInstallations(items);
      if (items.length === 1) setInstallation(String(items[0].id));
    }).catch((e) => setError(`GitHub App: ${String(e)}`));
  }, [mode]);

  useEffect(() => {
    const id = Number(installation);
    setRepos([]); setRepo("");
    if (!id) return;
    api.installationRepos(id).then(setRepos).catch((e) => setError(`Repositories: ${String(e)}`));
  }, [installation]);

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try {
      const selected = repos.find((item) => item.full_name === repo);
      const project = await api.createProject({
        name: name || selected?.name || repo.split("/").pop() || "Project",
        agent,
        ...(mode === "github"
          ? { repository_full_name: repo, installation_id: Number(installation), default_branch: selected?.default_branch || "main" }
          : { local_path: localPath }),
      });
      router.push(`/projects/${project.id}`);
    } catch (e) { setError(String(e)); setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-3xl font-semibold">Add project</h1>
      <p className="mt-2 text-zinc-400">Register a repository. AIpipe keeps orchestration in the backend, not in the browser.</p>
      <form onSubmit={submit} className="mt-8 space-y-5 rounded-2xl border border-white/10 bg-white/[0.035] p-6">
        <div className="flex rounded-xl bg-black/30 p-1 text-sm">
          {(["github", "local"] as const).map((item) => <button type="button" key={item} onClick={() => setMode(item)} className={`flex-1 rounded-lg px-3 py-2 ${mode === item ? "bg-white text-black" : "text-zinc-400"}`}>{item === "github" ? "GitHub" : "Local server path"}</button>)}
        </div>

        {mode === "github" ? <>
          <label className="block text-sm">GitHub App installation
            <select required value={installation} onChange={(e) => setInstallation(e.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5">
              <option value="">Select installation…</option>
              {installations.map((item) => <option key={item.id} value={item.id}>{item.account} · {item.id}</option>)}
            </select>
          </label>
          <label className="block text-sm">Repository
            <select required value={repo} onChange={(e) => { setRepo(e.target.value); if (!name) setName(e.target.value.split("/").pop() || ""); }} className="mt-2 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5">
              <option value="">Select repository…</option>
              {repos.map((item) => <option key={item.id} value={item.full_name}>{item.full_name}{item.private ? " · private" : ""}</option>)}
            </select>
          </label>
        </> : <label className="block text-sm">Local path on the AIpipe server<input required value={localPath} onChange={(e) => setLocalPath(e.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5" placeholder="/workspace/my-project" /></label>}

        <label className="block text-sm">Display name<input required value={name} onChange={(e) => setName(e.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5 outline-none focus:border-blue-400" placeholder="Backend API" /></label>
        <label className="block text-sm">Agent<select value={agent} onChange={(e) => setAgent(e.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2.5"><option value="codex">Codex</option><option value="claude">Claude Code</option></select></label>
        {error && <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">{error}</div>}
        <button disabled={busy} className="rounded-xl bg-white px-4 py-2.5 font-semibold text-black disabled:opacity-50">{busy ? "Adding…" : "Create project"}</button>
      </form>
    </div>
  );
}
