"use client";

import { useMemo, useState } from "react";
import { Check, UserCheck } from "lucide-react";
import { plural, type Run } from "@/lib/api";

type Props = { run: Run; busy: boolean; onDecision: (resume: Record<string, unknown>) => void };

export function Checkpoint(props: Props) {
  const kind = props.run.pending.checkpoint;
  if (kind === "protocol") return <ProtocolCheckpoint {...props} />;
  if (kind === "screening") return <ScreeningCheckpoint {...props} />;
  if (kind === "report") return <ReportCheckpoint {...props} />;
  return null;
}

function Head({ step, title, children }: { step: number; title: string; children: React.ReactNode }) {
  return (
    <div className="callout-head">
      <div className="callout-icon">
        <UserCheck size={17} />
      </div>
      <div>
        <h3>
          Checkpoint {step} of 3 · {title}
        </h3>
        <p>{children}</p>
      </div>
    </div>
  );
}

function ProtocolCheckpoint({ run, busy, onDecision }: Props) {
  const [mode, setMode] = useState<"" | "changes" | "edit">("");
  const [feedback, setFeedback] = useState("");
  const [json, setJson] = useState(() => JSON.stringify(run.pending.protocol, null, 2));
  const [jsonError, setJsonError] = useState("");

  function saveEdits() {
    try {
      onDecision({ action: "approve", protocol: JSON.parse(json) });
    } catch (e) {
      setJsonError(`Invalid JSON: ${(e as Error).message}`);
    }
  }

  return (
    <div className="callout">
      <Head step={1} title="Approve the protocol">
        The Planner wrote the protocol and the Search agent tested its queries on the live databases. Read them in the Protocol tab below,
        then decide. Nothing is retrieved before you approve.
      </Head>
      <div className="callout-actions">
        <button className="btn primary" disabled={busy} onClick={() => onDecision({ action: "approve" })}>
          <Check size={15} /> Approve
        </button>
        <button className="btn" disabled={busy} onClick={() => setMode(mode === "changes" ? "" : "changes")}>
          Request changes
        </button>
        <button className="btn ghost" disabled={busy} onClick={() => setMode(mode === "edit" ? "" : "edit")}>
          Edit it myself
        </button>
      </div>
      {mode === "changes" && (
        <div className="callout-body">
          <textarea className="input" autoFocus value={feedback} onChange={(e) => setFeedback(e.target.value)}
                    placeholder="e.g. Restrict to adults; add terms for telemonitoring" />
          <div className="callout-actions">
            <button className="btn primary" disabled={busy || !feedback.trim()} onClick={() => onDecision({ action: "revise", feedback: feedback.trim() })}>
              Send to the Planner
            </button>
          </div>
        </div>
      )}
      {mode === "edit" && (
        <div className="callout-body">
          <textarea className="input code" spellCheck={false} value={json} onChange={(e) => (setJson(e.target.value), setJsonError(""))} />
          {jsonError && <div className="hint" style={{ color: "var(--crit)" }}>{jsonError}</div>}
          <div className="callout-actions">
            <button className="btn primary" disabled={busy} onClick={saveEdits}>
              Save my edits and continue
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

type PendingDecision = { rid: string; title: string; final: string; resolved_by: string; a: string; b: string; rationale: string };

function ScreeningCheckpoint({ run, busy, onDecision }: Props) {
  const decisions: PendingDecision[] = run.pending.decisions;
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [all, setAll] = useState(false);
  const shown = useMemo(
    () => (all ? decisions : decisions.filter((d) => d.final === "include" || d.resolved_by !== "consensus")),
    [all, decisions],
  );
  const changed = Object.keys(overrides).length;

  function set(rid: string, original: string, value: string) {
    setOverrides((prev) => {
      const next = { ...prev };
      if (value === original) delete next[rid];
      else next[rid] = value;
      return next;
    });
  }

  return (
    <div className="callout">
      <Head step={2} title="Check the screening decisions">
        Two reviewers screened {decisions.length} records on title and abstract. Change any decision, then approve. Your changes are logged
        and reported in the manuscript.
      </Head>
      <div className="callout-body">
        <div className="toolbar">
          <div className="segmented sm">
            <button aria-pressed={!all} onClick={() => setAll(false)}>
              Retained and disputed ({decisions.filter((d) => d.final === "include" || d.resolved_by !== "consensus").length})
            </button>
            <button aria-pressed={all} onClick={() => setAll(true)}>
              All ({decisions.length})
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <div className="table-scroll" style={{ maxHeight: 380 }}>
            <table className="t">
              <thead>
                <tr>
                  <th>Record</th>
                  <th className="fit">Reviewers</th>
                  <th className="fit">Decision</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((d) => {
                  const value = overrides[d.rid] ?? d.final;
                  return (
                    <tr key={d.rid}>
                      <td>
                        <div style={{ fontWeight: 540 }}>{d.title}</div>
                        <div className="muted" style={{ fontSize: 12.5, marginTop: 2 }}>
                          {d.rid} · {d.rationale}
                        </div>
                      </td>
                      <td className="muted fit">
                        {d.a} / {d.b}
                        {d.resolved_by !== "consensus" && <div style={{ fontSize: 12 }}>settled by {d.resolved_by}</div>}
                      </td>
                      <td className="fit">
                        <div className="segmented sm">
                          <button aria-pressed={value === "include"} onClick={() => set(d.rid, d.final, "include")}>
                            Include
                          </button>
                          <button aria-pressed={value === "exclude"} onClick={() => set(d.rid, d.final, "exclude")}>
                            Exclude
                          </button>
                        </div>
                        {overrides[d.rid] && <div className="hint" style={{ color: "var(--warn)" }}>changed by you</div>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div className="callout-actions">
        <button className="btn primary" disabled={busy} onClick={() => onDecision({ action: "approve", overrides })}>
          <Check size={15} /> {changed ? `Approve with ${plural(changed, "change")}` : "Approve"}
        </button>
      </div>
    </div>
  );
}

function ReportCheckpoint({ run, busy, onDecision }: Props) {
  const [revising, setRevising] = useState(false);
  const [feedback, setFeedback] = useState("");
  const issues = run.pending.qa_report?.issues?.length ?? 0;

  return (
    <div className="callout">
      <Head step={3} title="Approve the manuscript">
        {issues
          ? `The Critic leaves ${plural(issues, "issue")} open: they are listed in the Quality tab below, and the draft is in the Report tab.`
          : "The Critic found no open issue. The draft is in the Report tab below."}{" "}
        Approve to export the final files, or ask the Writing agent for a revision.
      </Head>
      <div className="callout-actions">
        <button className="btn primary" disabled={busy} onClick={() => onDecision({ action: "approve" })}>
          <Check size={15} /> Approve and export
        </button>
        <button className="btn" disabled={busy} onClick={() => setRevising(!revising)}>
          Request a revision
        </button>
      </div>
      {revising && (
        <div className="callout-body">
          <textarea className="input" autoFocus value={feedback} onChange={(e) => setFeedback(e.target.value)}
                    placeholder="What should the Writing agent change?" />
          <div className="callout-actions">
            <button className="btn primary" disabled={busy || !feedback.trim()} onClick={() => onDecision({ action: "revise", feedback: feedback.trim() })}>
              Send to the Writing agent
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
