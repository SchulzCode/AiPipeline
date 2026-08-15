"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowLeft, CheckCircle, Plus, Trash, WarningCircle } from "@phosphor-icons/react";
import { api } from "@/lib/api";
import type { AgentModels, Project, ProjectConfigPatch, ProjectPipelineConfig } from "@/lib/types";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner } from "@/components/ui/error-banner";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

const FIELD = "rounded-md border border-border bg-surface-sunken px-3 py-2 text-sm text-fg focus-visible:border-accent disabled:opacity-50";
const CONTEXT_CLASSES = ["SHALLOW", "NORMAL", "DEEP"] as const;
const RISK_LEVELS = ["LOW", "MEDIUM", "HIGH"] as const;

export default function ProjectSettingsPage() {
  const { id } = useParams<{ id: string }>();

  const [project, setProject] = useState<Project | null>(null);
  const [agentModels, setAgentModels] = useState<AgentModels>({});
  const [source, setSource] = useState<"local" | "github" | "unavailable" | null>(null);
  const [editable, setEditable] = useState(true);
  const [warning, setWarning] = useState<string | null>(null);
  const [config, setConfig] = useState<ProjectPipelineConfig | null>(null);
  const [initialConfig, setInitialConfig] = useState<ProjectPipelineConfig | null>(null);
  const [identity, setIdentity] = useState({ agent: "codex", model: "" });
  const [initialIdentity, setInitialIdentity] = useState({ agent: "codex", model: "" });
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.project(id), api.projectConfig(id), api.agentModels()])
      .then(([p, c, models]) => {
        if (cancelled) return;
        setProject(p);
        setSource(c.source);
        setEditable(c.editable);
        setWarning(c.warning ?? null);
        setConfig(c.config);
        setInitialConfig(c.config);
        setIdentity({ agent: p.agent, model: p.model ?? "" });
        setInitialIdentity({ agent: p.agent, model: p.model ?? "" });
        setAgentModels(models);
      })
      .catch((e) => !cancelled && setError(String(e)));
    return () => {
      cancelled = true;
    };
  }, [id]);

  const dirty = useMemo(() => {
    if (!config || !initialConfig) return false;
    return JSON.stringify(config) !== JSON.stringify(initialConfig) || JSON.stringify(identity) !== JSON.stringify(initialIdentity);
  }, [config, initialConfig, identity, initialIdentity]);

  function set<K extends keyof ProjectPipelineConfig>(key: K, value: ProjectPipelineConfig[K]) {
    setConfig((prev) => (prev ? { ...prev, [key]: value } : prev));
    setSaved(false);
  }

  async function save() {
    if (!config || !initialConfig || !project) return;
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const patch: ProjectConfigPatch = {};
      for (const key of Object.keys(config) as (keyof ProjectPipelineConfig)[]) {
        if (JSON.stringify(config[key]) !== JSON.stringify(initialConfig[key])) {
          (patch as Record<string, unknown>)[key] = config[key];
        }
      }
      if (Object.keys(patch).length > 0) {
        const updated = await api.updateProjectConfig(id, patch);
        setConfig(updated.config);
        setInitialConfig(updated.config);
      }
      if (identity.agent !== initialIdentity.agent || identity.model !== initialIdentity.model) {
        const updatedProject = await api.updateProject(id, { agent: identity.agent, model: identity.model || null });
        setProject(updatedProject);
        setInitialIdentity({ agent: updatedProject.agent, model: updatedProject.model ?? "" });
      }
      setSaved(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!project || !config) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <Link href={`/projects/${id}`} className="inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg">
          <ArrowLeft size={13} aria-hidden="true" />
          {project.name}
        </Link>
        <h1 className="mt-2 text-xl font-semibold tracking-tight text-fg">Project settings</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Pipeline configuration for this project, stored in <code className="font-mono text-fg">.ai/config.yml</code>
          {source === "github" ? " and committed directly to the default branch when saved" : ""}.
        </p>
      </div>

      {error ? <ErrorBanner message={error} /> : null}
      {warning ? (
        <div className="flex items-center gap-2 rounded-md border border-status-attention/30 bg-status-attention/10 px-3 py-2 text-xs text-status-attention">
          <WarningCircle size={14} weight="bold" aria-hidden="true" />
          {warning}
        </div>
      ) : null}
      {!editable ? (
        <div className="flex items-center gap-2 rounded-md border border-status-queued/30 bg-status-queued/10 px-3 py-2 text-xs text-status-queued">
          Configuration cannot be edited for this project (no local path or GitHub installation on record).
        </div>
      ) : null}
      {saved ? (
        <div className="flex items-center gap-2 rounded-md border border-status-done/30 bg-status-done/10 px-3 py-2 text-xs text-status-done">
          <CheckCircle size={14} weight="bold" aria-hidden="true" />
          Saved.
        </div>
      ) : null}

      <Card>
        <CardHeader title="Agent" description="Which coding agent and model run tasks for this project." />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label="Agent">
            <select
              disabled={!editable}
              className={FIELD}
              value={identity.agent}
              onChange={(e) => setIdentity({ agent: e.target.value, model: "" })}
            >
              <option value="codex">Codex</option>
              <option value="claude">Claude Code</option>
            </select>
          </Field>
          <Field label="Model">
            <select disabled={!editable} className={FIELD} value={identity.model} onChange={(e) => setIdentity((prev) => ({ ...prev, model: e.target.value }))}>
              {(agentModels[identity.agent] || []).map((m) => (
                <option key={m.id ?? ""} value={m.id ?? ""}>
                  {m.label}
                </option>
              ))}
            </select>
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Git & merge" description="Target branch and how successful pull requests land." />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <Field label="Main branch">
            <input disabled={!editable} className={FIELD} value={config.main_branch} onChange={(e) => set("main_branch", e.target.value)} />
          </Field>
          <Field label="Merge method">
            <select disabled={!editable} className={FIELD} value={config.merge_method} onChange={(e) => set("merge_method", e.target.value)}>
              <option value="squash">Squash</option>
              <option value="merge">Merge commit</option>
              <option value="rebase">Rebase</option>
            </select>
          </Field>
          <ToggleField label="Auto-merge" description="Merge automatically once every gate passes." checked={config.auto_merge} disabled={!editable} onChange={(v) => set("auto_merge", v)} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Timeouts & retry budgets" description="How long steps may run and how many times AIpipe retries before blocking." />
        <CardBody className="grid gap-4 sm:grid-cols-3">
          <NumField label="Command timeout (s)" value={config.command_timeout_seconds} min={30} max={21600} disabled={!editable} onChange={(v) => set("command_timeout_seconds", v)} />
          <NumField label="CI timeout (s)" value={config.ci_timeout_seconds} min={60} max={21600} disabled={!editable} onChange={(v) => set("ci_timeout_seconds", v)} />
          <NumField label="CI registration grace (s)" value={config.ci_registration_grace_seconds} min={0} max={3600} disabled={!editable} onChange={(v) => set("ci_registration_grace_seconds", v)} />
          <NumField label="Implementation attempts" value={config.implementation_attempts} min={1} max={10} disabled={!editable} onChange={(v) => set("implementation_attempts", v)} />
          <NumField label="Verification attempts" value={config.verification_attempts} min={1} max={10} disabled={!editable} onChange={(v) => set("verification_attempts", v)} />
          <NumField label="Review attempts" value={config.review_attempts} min={1} max={10} disabled={!editable} onChange={(v) => set("review_attempts", v)} />
          <NumField label="CI attempts" value={config.ci_attempts} min={1} max={10} disabled={!editable} onChange={(v) => set("ci_attempts", v)} />
          <NumField label="External-call attempts" value={config.external_attempts} min={1} max={10} disabled={!editable} onChange={(v) => set("external_attempts", v)} />
          <NumField label="External backoff (s)" value={config.external_backoff_seconds} min={0} max={60} step={0.5} disabled={!editable} onChange={(v) => set("external_backoff_seconds", v)} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Planner" description="A read-only planning pass that runs before implementation for deep-context tasks." />
        <CardBody className="grid gap-4 sm:grid-cols-2">
          <ToggleField label="Planner enabled" checked={config.planner_enabled} disabled={!editable} onChange={(v) => set("planner_enabled", v)} />
          <NumField label="Planner attempts" value={config.planner_attempts} min={1} max={10} disabled={!editable} onChange={(v) => set("planner_attempts", v)} />
          <div className="sm:col-span-2">
            <MultiSelectField
              label="Runs for context classes"
              options={CONTEXT_CLASSES}
              selected={config.planner_context_classes}
              disabled={!editable}
              onChange={(v) => set("planner_context_classes", v)}
            />
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Feature discovery" description="Bounds on autonomous discovery: how many candidates to propose, file, and optionally auto-implement." />
        <CardBody className="grid gap-4 sm:grid-cols-3">
          <NumField label="Max candidates" value={config.discovery_max_candidates} min={0} max={50} disabled={!editable} onChange={(v) => set("discovery_max_candidates", v)} />
          <NumField label="Max new issues" value={config.discovery_max_new_issues} min={0} max={50} disabled={!editable} onChange={(v) => set("discovery_max_new_issues", v)} />
          <NumField label="Max auto-implement" value={config.discovery_max_auto_implement} min={0} max={20} disabled={!editable} onChange={(v) => set("discovery_max_auto_implement", v)} />
          <Field label="Max risk to auto-implement">
            <select disabled={!editable} className={FIELD} value={config.discovery_max_risk} onChange={(e) => set("discovery_max_risk", e.target.value)}>
              {RISK_LEVELS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Max context class to auto-implement">
            <select disabled={!editable} className={FIELD} value={config.discovery_max_context_class} onChange={(e) => set("discovery_max_context_class", e.target.value)}>
              {CONTEXT_CLASSES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </Field>
          <NumField label="Discovery attempts" value={config.discovery_attempts} min={1} max={10} disabled={!editable} onChange={(v) => set("discovery_attempts", v)} />
        </CardBody>
        <p className="border-t border-border px-5 py-3 text-xs text-fg-faint">
          Auto-implementation defaults to 0 (off). Discovered candidates are always queued as ordinary tasks — every quality, review, security, and CI gate still applies.
        </p>
      </Card>

      <Card>
        <CardHeader title="Setup, quality & security commands" description="Shell commands AIpipe runs in the worktree. Leave empty to auto-detect from the repository." />
        <CardBody className="space-y-5">
          <ToggleField label="Auto-detect setup commands" checked={config.setup_auto} disabled={!editable} onChange={(v) => set("setup_auto", v)} />
          <CommandMapEditor label="Setup commands" commands={config.setup_commands} disabled={!editable} onChange={(v) => set("setup_commands", v)} />
          <CommandMapEditor label="Quality commands" commands={config.quality_commands} disabled={!editable} onChange={(v) => set("quality_commands", v)} />
          <CommandMapEditor label="Security commands" commands={config.security_commands} disabled={!editable} onChange={(v) => set("security_commands", v)} />
        </CardBody>
      </Card>

      <div className="sticky bottom-4 flex justify-end">
        <Button variant="primary" disabled={!editable || !dirty || busy} onClick={save}>
          {busy ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5 text-xs font-medium text-fg-muted">
      {label}
      {children}
    </label>
  );
}

function NumField({
  label,
  value,
  min,
  max,
  step = 1,
  disabled,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  disabled?: boolean;
  onChange: (value: number) => void;
}) {
  // Local text mirrors the input while the user is mid-edit. Clamping on
  // every keystroke breaks "select all and retype": clearing the field would
  // otherwise immediately snap to `min`, and the next typed digit would
  // concatenate onto it instead of replacing it. Clamp only on blur/commit.
  // Resetting `text` when `value` changes externally (e.g. after a save) is
  // done during render rather than via an effect, per React's guidance on
  // adjusting state without extra render passes.
  const [text, setText] = useState(String(value));
  const [syncedValue, setSyncedValue] = useState(value);
  if (value !== syncedValue) {
    setSyncedValue(value);
    setText(String(value));
  }

  function commit(raw: string) {
    const next = Number(raw);
    const clamped = Number.isFinite(next) ? Math.min(max, Math.max(min, next)) : value;
    setText(String(clamped));
    if (clamped !== value) onChange(clamped);
  }

  return (
    <Field label={label}>
      <input
        type="number"
        className={`${FIELD} tabular-nums`}
        value={text}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => setText(e.target.value)}
        onBlur={(e) => commit(e.target.value)}
      />
    </Field>
  );
}

function ToggleField({
  label,
  description,
  checked,
  disabled,
  onChange,
}: {
  label: string;
  description?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-3">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 rounded-sm accent-[var(--color-accent)]"
      />
      <span>
        <span className="block text-sm text-fg">{label}</span>
        {description ? <span className="block text-xs text-fg-muted">{description}</span> : null}
      </span>
    </label>
  );
}

function MultiSelectField({
  label,
  options,
  selected,
  disabled,
  onChange,
}: {
  label: string;
  options: readonly string[];
  selected: string[];
  disabled?: boolean;
  onChange: (value: string[]) => void;
}) {
  function toggle(option: string) {
    if (disabled) return;
    onChange(selected.includes(option) ? selected.filter((o) => o !== option) : [...selected, option]);
  }
  return (
    <Field label={label}>
      <div className="flex gap-2">
        {options.map((option) => {
          const active = selected.includes(option);
          return (
            <button
              type="button"
              key={option}
              disabled={disabled}
              onClick={() => toggle(option)}
              aria-pressed={active}
              className={`rounded-pill px-3 py-1.5 text-xs font-medium transition-colors duration-150 disabled:opacity-50 ${
                active ? "bg-accent-solid text-accent-fg" : "border border-border bg-surface text-fg-muted"
              }`}
            >
              {option}
            </button>
          );
        })}
      </div>
    </Field>
  );
}

function CommandMapEditor({
  label,
  commands,
  disabled,
  onChange,
}: {
  label: string;
  commands: Record<string, string>;
  disabled?: boolean;
  onChange: (value: Record<string, string>) => void;
}) {
  const entries = Object.entries(commands);

  function updateEntry(index: number, key: string, value: string) {
    const next = [...entries];
    next[index] = [key, value];
    onChange(Object.fromEntries(next));
  }

  function removeEntry(index: number) {
    const next = entries.filter((_, i) => i !== index);
    onChange(Object.fromEntries(next));
  }

  function addEntry() {
    onChange({ ...commands, [`command_${entries.length + 1}`]: "" });
  }

  return (
    <div>
      <p className="text-xs font-medium text-fg-muted">{label}</p>
      <div className="mt-2 space-y-2">
        {entries.map(([key, value], index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              className={`${FIELD} w-32 shrink-0 font-mono text-xs`}
              value={key}
              disabled={disabled}
              onChange={(e) => updateEntry(index, e.target.value, value)}
              placeholder="name"
            />
            <input
              className={`${FIELD} flex-1 font-mono text-xs`}
              value={value}
              disabled={disabled}
              onChange={(e) => updateEntry(index, key, e.target.value)}
              placeholder="shell command"
            />
            <button type="button" disabled={disabled} onClick={() => removeEntry(index)} aria-label={`Remove ${key || "command"}`} className="shrink-0 rounded-md p-2 text-fg-faint hover:text-status-failed disabled:opacity-50">
              <Trash size={14} aria-hidden="true" />
            </button>
          </div>
        ))}
        <button
          type="button"
          disabled={disabled}
          onClick={addEntry}
          className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:text-accent-hover disabled:opacity-50"
        >
          <Plus size={12} aria-hidden="true" />
          Add command
        </button>
      </div>
    </div>
  );
}
