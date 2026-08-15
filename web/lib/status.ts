/**
 * Single source of truth for status -> tone -> color mapping across the app.
 * Every raw status string AIpipe produces (project, task, activity, CI,
 * review, discovery) reduces to one of these six operational tones, always
 * rendered with the same color so a user only has to learn the palette once.
 */
export type Tone = "active" | "done" | "queued" | "attention" | "failed" | "idle";

export const TONE_META: Record<Tone, { label: string; dot: string; text: string; bg: string; border: string }> = {
  active: { label: "Active", dot: "bg-status-active", text: "text-status-active", bg: "bg-status-active/10", border: "border-status-active/30" },
  done: { label: "Done", dot: "bg-status-done", text: "text-status-done", bg: "bg-status-done/10", border: "border-status-done/30" },
  queued: { label: "Queued", dot: "bg-status-queued", text: "text-status-queued", bg: "bg-status-queued/10", border: "border-status-queued/25" },
  attention: { label: "Attention", dot: "bg-status-attention", text: "text-status-attention", bg: "bg-status-attention/10", border: "border-status-attention/30" },
  failed: { label: "Failed", dot: "bg-status-failed", text: "text-status-failed", bg: "bg-status-failed/10", border: "border-status-failed/30" },
  idle: { label: "Idle", dot: "bg-status-idle", text: "text-status-idle", bg: "bg-status-idle/10", border: "border-status-idle/25" },
};

const TASK_STATUS_TONE: Record<string, Tone> = {
  QUEUED: "queued",
  CLAIMED: "active",
  ROUTING: "active",
  PREPARING: "active",
  DISCOVERY: "active",
  DISCOVERING: "active",
  PLANNING: "active",
  IMPLEMENTING: "active",
  VERIFYING: "active",
  REVIEWING: "active",
  PR_OPEN: "active",
  CI: "active",
  MERGING: "active",
  POST_MERGE: "active",
  DONE: "done",
  BLOCKED: "attention",
  NEEDS_INPUT: "attention",
  FAILED: "failed",
  CANCELLED: "idle",
};

const TASK_STATUS_LABEL: Record<string, string> = {
  QUEUED: "Queued",
  CLAIMED: "Claimed",
  ROUTING: "Routing",
  PREPARING: "Preparing",
  DISCOVERY: "Discovery",
  DISCOVERING: "Discovering",
  PLANNING: "Planning",
  IMPLEMENTING: "Implementing",
  VERIFYING: "Verifying",
  REVIEWING: "Reviewing",
  PR_OPEN: "PR open",
  CI: "CI running",
  MERGING: "Merging",
  POST_MERGE: "Post-merge",
  DONE: "Done",
  BLOCKED: "Blocked",
  NEEDS_INPUT: "Needs input",
  FAILED: "Failed",
  CANCELLED: "Cancelled",
};

const PROJECT_STATUS_TONE: Record<string, Tone> = {
  IDLE: "idle",
  BUSY: "active",
};

const ACTIVITY_STATUS_TONE: Record<string, Tone> = {
  info: "active",
  success: "done",
  warning: "attention",
  error: "failed",
};

const DISCOVERY_STATUS_TONE: Record<string, Tone> = {
  proposed: "queued",
  duplicate: "idle",
  created: "done",
  failed: "failed",
};

export function taskTone(status: string): Tone {
  return TASK_STATUS_TONE[status] ?? "active";
}

export function taskStatusLabel(status: string): string {
  return TASK_STATUS_LABEL[status] ?? status;
}

export function projectTone(status: string): Tone {
  return PROJECT_STATUS_TONE[status] ?? "idle";
}

export function activityTone(status: string): Tone {
  return ACTIVITY_STATUS_TONE[status] ?? "active";
}

export function discoveryTone(status: string): Tone {
  return DISCOVERY_STATUS_TONE[status] ?? "queued";
}

export const ATTENTION_TASK_STATUSES = new Set(["BLOCKED", "NEEDS_INPUT"]);
export const FAILED_TASK_STATUSES = new Set(["FAILED"]);
export const TERMINAL_TASK_STATUSES = new Set(["DONE", "BLOCKED", "FAILED", "CANCELLED"]);
export const ACTIVE_TASK_STATUSES = new Set([
  "CLAIMED", "ROUTING", "PREPARING", "DISCOVERY", "DISCOVERING", "PLANNING",
  "IMPLEMENTING", "VERIFYING", "REVIEWING", "PR_OPEN", "CI", "MERGING", "POST_MERGE",
]);

export function needsAttention(status: string): boolean {
  return ATTENTION_TASK_STATUSES.has(status) || FAILED_TASK_STATUSES.has(status);
}
