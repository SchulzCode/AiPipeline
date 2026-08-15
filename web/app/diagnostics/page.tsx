"use client";

import { useEffect, useState } from "react";
import { CheckCircle, Database, GithubLogo, ShieldWarning, Users, WarningCircle, XCircle, type Icon } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { SystemHealth } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Skeleton } from "@/components/ui/skeleton";
import { TONE_META, type Tone } from "@/lib/status";

export default function DiagnosticsPage() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      try {
        const data = await api.systemHealth();
        if (!cancelled) {
          setHealth(data);
          setError("");
        }
      } catch (e) {
        if (!cancelled) setError(String(e));
      }
    }
    refresh();
    const interval = window.setInterval(refresh, 10000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-fg">Diagnostics</h1>
        <p className="mt-1 text-sm text-fg-muted">System health, derived from current project and task state — not a separate process registry.</p>
      </div>

      {error ? <ErrorBanner message={error} /> : null}

      {!health && !error ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : health ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard icon={Database} label="Projects" value={health.projects_total} detail={formatCounts(health.projects_by_status)} />
            <MetricCard icon={Users} label="Active workers" value={health.active_workers} detail={`heartbeat within ${Math.round(health.worker_stale_seconds)}s`} tone={health.active_workers > 0 ? "active" : "idle"} />
            <MetricCard icon={WarningCircle} label="Stale claims" value={health.stale_tasks} detail="claimed, no recent heartbeat" tone={health.stale_tasks > 0 ? "attention" : "done"} />
            <MetricCard icon={CheckCircle} label="Active tasks" value={health.active_tasks} detail={formatCounts(health.tasks_by_status)} />
          </div>

          <Card>
            <CardHeader title="Configuration" description="Non-secret configuration presence — no credentials are ever exposed here." />
            <CardBody className="grid gap-3 sm:grid-cols-3">
              <ConfigRow icon={GithubLogo} label="GitHub App" ok={health.github_app_configured} okLabel="Configured" badLabel="Not configured" />
              <ConfigRow icon={ShieldWarning} label="GitHub login" ok={health.github_login_configured} okLabel="Configured" badLabel="Not configured" />
              <ConfigRow icon={Database} label="Database" ok neutralLabel={health.database} />
              {health.dev_auth ? (
                <div className="sm:col-span-3">
                  <div className="flex items-center gap-2 rounded-md border border-status-attention/30 bg-status-attention/10 px-3 py-2 text-xs text-status-attention">
                    <WarningCircle size={14} weight="bold" aria-hidden="true" />
                    Dev auth is enabled — anyone can sign in without GitHub OAuth. Disable for production deployments.
                  </div>
                </div>
              ) : null}
            </CardBody>
          </Card>
        </>
      ) : null}
    </div>
  );
}

function formatCounts(counts: Record<string, number>): string {
  const entries = Object.entries(counts);
  if (entries.length === 0) return "none";
  return entries.map(([k, v]) => `${v} ${k.toLowerCase()}`).join(" · ");
}

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: Icon;
  label: string;
  value: number;
  detail?: string;
  tone?: Tone;
}) {
  const meta = tone ? TONE_META[tone] : null;
  return (
    <Card className="p-4">
      <div className="flex items-center gap-2 text-fg-muted">
        <Icon size={15} aria-hidden="true" />
        <span className="text-xs font-medium">{label}</span>
      </div>
      <p className={`mt-2 text-2xl font-semibold tabular-nums ${meta ? meta.text : "text-fg"}`}>{value}</p>
      {detail ? <p className="mt-1 text-xs text-fg-faint">{detail}</p> : null}
    </Card>
  );
}

function ConfigRow({
  icon: Icon,
  label,
  ok,
  okLabel,
  badLabel,
  neutralLabel,
}: {
  icon: Icon;
  label: string;
  ok: boolean;
  okLabel?: string;
  badLabel?: string;
  neutralLabel?: string;
}) {
  return (
    <div className="flex items-center gap-2.5 rounded-md border border-border bg-surface-sunken px-3 py-2.5">
      <Icon size={16} className="shrink-0 text-fg-muted" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <p className="text-xs text-fg-muted">{label}</p>
        <p className="text-sm text-fg">{neutralLabel ?? (ok ? okLabel : badLabel)}</p>
      </div>
      {neutralLabel ? null : ok ? (
        <CheckCircle size={16} weight="fill" className="shrink-0 text-status-done" aria-hidden="true" />
      ) : (
        <XCircle size={16} weight="fill" className="shrink-0 text-status-attention" aria-hidden="true" />
      )}
    </div>
  );
}
