import { taskTone, projectTone, activityTone, discoveryTone, taskStatusLabel, TONE_META, type Tone } from "@/lib/status";

function Pill({ tone, label, pulse }: { tone: Tone; label: string; pulse?: boolean }) {
  const meta = TONE_META[tone];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-1 text-xs font-medium leading-none whitespace-nowrap ${meta.bg} ${meta.border} ${meta.text}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${meta.dot} ${pulse ? "animate-live-pulse" : ""}`} aria-hidden="true" />
      {label}
    </span>
  );
}

export function TaskStatusBadge({ status }: { status: string }) {
  const tone = taskTone(status);
  return <Pill tone={tone} label={taskStatusLabel(status)} pulse={tone === "active"} />;
}

export function ProjectStatusBadge({ status }: { status: string }) {
  const tone = projectTone(status);
  return <Pill tone={tone} label={tone === "active" ? "Working" : "Idle"} pulse={tone === "active"} />;
}

export function ActivityStatusBadge({ status, label }: { status: string; label: string }) {
  return <Pill tone={activityTone(status)} label={label} />;
}

export function DiscoveryStatusBadge({ status }: { status: string }) {
  return <Pill tone={discoveryTone(status)} label={status} />;
}

export function ToneBadge({ tone, label, pulse }: { tone: Tone; label: string; pulse?: boolean }) {
  return <Pill tone={tone} label={label} pulse={pulse} />;
}
