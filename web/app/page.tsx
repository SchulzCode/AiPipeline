"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Project } from "@/lib/types";
import { StatusBadge } from "@/components/status-badge";

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { api.projects().then(setProjects).catch((e) => setError(String(e))); }, []);
  return (
    <div>
      <div className="mb-8 flex items-end justify-between gap-6">
        <div>
          <div className="text-sm uppercase tracking-[0.2em] text-blue-300">Control Center</div>
          <h1 className="mt-2 text-4xl font-semibold tracking-tight">Projects</h1>
          <p className="mt-2 text-zinc-400">One place to launch and observe autonomous engineering tasks.</p>
        </div>
        <Link href="/projects/new" className="rounded-xl bg-white px-4 py-2.5 font-semibold text-black">+ Add project</Link>
      </div>
      {error && <div className="mb-5 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-rose-200">{error}</div>}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {projects.map((project) => (
          <Link key={project.id} href={`/projects/${project.id}`} className="rounded-2xl border border-white/10 bg-white/[0.035] p-5 transition hover:border-white/20 hover:bg-white/[0.055]">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{project.name}</h2>
                <p className="mt-1 truncate text-sm text-zinc-500">{project.repository_full_name || project.local_path}</p>
              </div>
              <StatusBadge status={project.status} />
            </div>
            <div className="mt-7 flex gap-5 text-xs text-zinc-500">
              <span>Agent: {project.agent}</span><span>Branch: {project.default_branch}</span>
            </div>
          </Link>
        ))}
        {!projects.length && !error && <div className="rounded-2xl border border-dashed border-white/15 p-8 text-zinc-500">No projects yet. Add a GitHub or local repository.</div>}
      </div>
    </div>
  );
}
