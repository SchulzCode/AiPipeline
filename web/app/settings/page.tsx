"use client";

import { useEffect, useState } from "react";
import { API } from "@/lib/api";

export default function SettingsPage() {
  const [settings, setSettings] = useState<Record<string, unknown> | null>(null);
  useEffect(() => { fetch(`${API}/settings`, { credentials: "include" }).then((r) => r.json()).then(setSettings); }, []);
  return <div className="max-w-2xl"><h1 className="text-3xl font-semibold">Settings</h1><p className="mt-2 text-zinc-400">Runtime capabilities are configured through server environment variables; secrets are never returned here.</p><pre className="mt-6 rounded-2xl border border-white/10 bg-black/30 p-5 text-sm text-zinc-300">{JSON.stringify(settings, null, 2)}</pre></div>;
}
