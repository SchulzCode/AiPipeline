"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API, api } from "@/lib/api";
import type { User } from "@/lib/types";

export function Shell({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => { api.me().then(setUser).catch(() => setUser(null)); }, []);
  if (user === undefined) return <main className="mx-auto max-w-6xl p-8 text-zinc-400">Loading AIpipe…</main>;
  if (user === null) {
    return (
      <main className="mx-auto flex min-h-screen max-w-xl items-center p-8">
        <div className="w-full rounded-3xl border border-white/10 bg-black/30 p-8 shadow-2xl">
          <div className="mb-2 text-sm font-semibold uppercase tracking-[0.2em] text-blue-300">AIpipe</div>
          <h1 className="text-3xl font-semibold">Engineering control center</h1>
          <p className="mt-3 text-zinc-400">Sign in to manage projects and autonomous software tasks.</p>
          <a className="mt-7 inline-flex rounded-xl bg-white px-4 py-2.5 font-semibold text-black" href={`${API}/auth/github/login`}>Sign in with GitHub</a>
        </div>
      </main>
    );
  }
  return (
    <div className="min-h-screen">
      <header className="border-b border-white/10 bg-black/20 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-7">
            <Link href="/" className="font-semibold tracking-tight">AIpipe</Link>
            <nav className="flex gap-5 text-sm text-zinc-400">
              <Link href="/">Projects</Link>
              <Link href="/settings">Settings</Link>
            </nav>
          </div>
          <div className="text-sm text-zinc-400">@{user.login}</div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </div>
  );
}
