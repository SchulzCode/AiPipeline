export type User = { id: string; login: string; avatar_url?: string | null };
export type Project = {
  id: string;
  name: string;
  repository_full_name?: string | null;
  repository_url?: string | null;
  local_path?: string | null;
  installation_id?: number | null;
  default_branch: string;
  agent: "codex" | "claude" | string;
  model?: string | null;
  enabled: boolean;
  status: string;
  created_at: string;
};
export type AgentModelOption = { id: string | null; label: string };
export type AgentModels = Record<string, AgentModelOption[]>;
export type Task = {
  id: string;
  project_id: string;
  source: string;
  source_reference?: string | null;
  title?: string | null;
  prompt: string;
  status: string;
  risk?: string | null;
  context_class?: string | null;
  core_task_id?: string | null;
  discovery_task_id?: string | null;
  branch?: string | null;
  pr_number?: number | null;
  error?: string | null;
  failure_category?: string | null;
  worker_build?: string | null;
  input_tokens: number;
  output_tokens: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};
export type Event = { id: number; task_id: string; kind: string; detail?: string | null; created_at: string };
export type Issue = { number: number; title: string; state: string; url: string; labels: string[] };

export type ActivityStatus = "info" | "success" | "warning" | "error";

export type ActivityItem = {
  category: string;
  title: string;
  summary: string;
  result?: string | null;
  next_step?: string | null;
  status: ActivityStatus;
  timestamp: string;
  duration_seconds?: number | null;
  technical_event_id?: number | null;
};

export type CurrentActivity = {
  title: string;
  summary: string;
  phase: string;
  started_at: string;
  next_step?: string | null;
  agent_label: string;
};

export type Blocker = { reason: string; last_phase?: string | null; category?: string | null };

export type CheckStatus = { type: string; name: string; status: string; updated_at: string };
export type ReviewSummary = { status: ActivityStatus; result: string; updated_at: string };
export type CiSummary = { total: number; passed: number; failed: number };
export type PlanSummary = { status: ActivityStatus; plan: string; updated_at: string };
export type ChecksSummary = {
  checks: CheckStatus[];
  review?: ReviewSummary | null;
  security_review?: ReviewSummary | null;
  ci?: CiSummary | null;
  plan?: PlanSummary | null;
};

export type ActivityFeed = {
  items: ActivityItem[];
  current?: CurrentActivity | null;
  blocker?: Blocker | null;
  checks: ChecksSummary;
};

export type Installation = { id: number; account: string; target_type?: string | null };
export type Repository = { id: number; name: string; full_name: string; private: boolean; default_branch: string };

export type FeatureCandidate = {
  key: string;
  title: string;
  summary: string;
  rationale?: string;
  acceptance_criteria: string[];
  task_type: string;
  risk: string;
  context_class: string;
  labels: string[];
  score: number;
  rank?: number | null;
  status: "proposed" | "duplicate" | "created" | "failed";
  duplicate_of?: string | null;
  issue_number?: number | null;
  issue_url?: string | null;
  error?: string | null;
  handoff: boolean;
};

export type DiscoverySummary = {
  status: "pending" | "ready";
  candidates: FeatureCandidate[];
  created: string[];
  duplicates: string[];
  failed: string[];
  handoff_issue_numbers: number[];
  updated_at?: string | null;
};
