// Types and helpers for the Python API (src/sysrev/api.py).

export type RunState = "running" | "waiting" | "finished" | "error" | "paused";

export type RunSummary = { id: string; question: string; created: string; state: RunState; included: number | null };

export type Step = { key: string; name: string; kind: "agent" | "human"; state: "done" | "now" | "todo" };

export type Criterion = { id: string; text: string; full_text_only?: boolean };

export type Protocol = {
  title: string;
  framework: string;
  framework_elements: Record<string, string>;
  inclusion_criteria: Criterion[];
  exclusion_criteria: Criterion[];
  study_designs: string[];
  outcomes: string[];
  data_items: string[];
  risk_of_bias_approach: string;
  synthesis_plan: string;
};

export type Strategy = {
  concepts: { name: string; free_text_terms: string[]; controlled_terms: string[] }[];
  queries: Record<string, string>;
  hit_counts: Record<string, number>;
  rationale: string;
  refinement_log: string[];
  databases?: { key: string; name: string; query: string; hits: number | null }[];
};

export type Flow = {
  identified: Record<string, number>;
  sources: { name: string; n: number }[];
  duplicates_removed: number;
  removed_by_automation: number;
  records_screened: number;
  records_excluded: number;
  reports_sought: number;
  reports_not_retrieved: number;
  reports_assessed: number;
  assessed_on_abstract_only: number;
  reports_excluded: Record<string, number>;
  studies_included: number;
};

export type Agreement = {
  n: number;
  raw_agreement: number;
  cohen_kappa: number | null;
  interpretation: string;
  conflicts: number;
} | null;

export type Decision = {
  rid: string;
  title: string;
  final: "include" | "exclude";
  a: string;
  b: string;
  resolved_by: string;
  why: string;
  reason: string;
  a_why: string;
  b_why: string;
};

export type Study = {
  rid: string;
  title: string;
  ref: string;
  venue: string;
  url: string;
  design: string;
  sample: string;
  basis: string;
  findings: string[];
  items: { field: string; value: string; quote: string; verified: boolean | null }[];
  quotes: { verified: number; checked: number };
  rob: { tool: string; overall: string; why: string; domains: { domain: string; judgement: string; why: string }[] } | null;
};

export type Issue = { severity: "critical" | "major" | "minor"; area: string; description: string; suggested_fix?: string | null };

export type QA = { verdict: string; issues: Issue[]; checks: Record<string, any> };

export type Run = {
  id: string;
  question: string;
  created: string;
  options: Record<string, any>;
  models: Record<string, string>;
  status: { state: RunState; label: string; current: string | null; error: string | null; steps: Step[]; waiting_for_quota: boolean; elsewhere: boolean };
  pending: any | null;
  flow: Flow | null;
  protocol: Protocol | null;
  strategy: Strategy | null;
  briefs: { stage: string; guidance: string }[];
  agreement: { title_abstract: Agreement; full_text: Agreement };
  screening: { title_abstract: Decision[]; full_text: Decision[] };
  studies: Study[];
  themes: { name: string; studies: number; certainty: string | null }[];
  qa: QA | null;
  evaluation: Record<string, any> | null;
  timings: { key: string; name: string; minutes: number }[];
  report: { file: string; final: boolean; words: number } | null;
  files: string[];
  audit_events: number;
};

export type Quota = { model: string; short: string; available: number; per_day: number; used_24h: number; tasks: string[] };

export type AuditEvent = { seq: number; time: string; agent: string; action: string; details: Record<string, unknown> };

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parse(res: Response) {
  if (res.ok) return res.json();
  let message = res.status >= 500 ? "The Python API is not reachable. Start it with: sysrev web" : `Request failed (${res.status})`;
  try {
    const body = await res.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail) && body.detail[0]?.msg) message = body.detail[0].msg;
  } catch {}
  throw new ApiError(res.status, message);
}

export const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(parse);

export const post = (url: string, body: unknown = {}) =>
  fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(parse);

export const fileUrl = (runId: string, name: string) => `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`;

export function formatDate(iso: string, withTime = false): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  const day = d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return withTime ? `${day}, ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}` : day;
}

export const plural = (n: number, word: string, many = word + "s") => `${n} ${n === 1 ? word : many}`;

export const kappa = (a: Agreement) => (a && a.cohen_kappa !== null && a.cohen_kappa !== undefined ? a.cohen_kappa.toFixed(2) : "—");
