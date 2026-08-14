"use client";

import { useEffect, useState } from "react";

export function formatDuration(totalSeconds: number): string {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(secs).padStart(2, "0")}s`;
  if (minutes > 0) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
  return `${secs}s`;
}

function elapsedSeconds(startedAt: string, endedAt?: string | null): number {
  const start = new Date(startedAt).getTime();
  const end = endedAt ? new Date(endedAt).getTime() : Date.now();
  return (end - start) / 1000;
}

// Reads `started_at`/`completed_at` (the persisted source of truth) and ticks
// locally every second instead of depending on the SSE stream for updates,
// so the timer survives refresh/reconnect and doesn't need a backend tick.
// The interval only forces a re-render; the value itself is recomputed fresh
// from wall-clock time on every render so it can't drift.
export function useElapsedSeconds(startedAt?: string | null, endedAt?: string | null): number | null {
  const [, forceTick] = useState(0);

  useEffect(() => {
    if (!startedAt || endedAt) return; // Nothing to tick: not started yet, or frozen at a final duration.
    const timer = window.setInterval(() => forceTick((t) => t + 1), 1000);
    return () => window.clearInterval(timer);
  }, [startedAt, endedAt]);

  return startedAt ? elapsedSeconds(startedAt, endedAt) : null;
}

export function TaskTimer({
  startedAt,
  endedAt,
  notStartedLabel = "Not started yet",
  className,
}: {
  startedAt?: string | null;
  endedAt?: string | null;
  notStartedLabel?: string;
  className?: string;
}) {
  const seconds = useElapsedSeconds(startedAt, endedAt);
  if (seconds === null) return <span className={className}>{notStartedLabel}</span>;
  return <span className={className}>{formatDuration(seconds)}</span>;
}
