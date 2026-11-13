"use client";

import { useState } from "react";
import useSWR from "swr";
import { ChartNoAxesColumn, History, Info, TriangleAlert } from "lucide-react";
import { fetcher, plural, post, type AuditEvent, type Issue, type Run } from "@/lib/api";
import { Bars, Card, Disclosure, Empty, Stat } from "../ui";

const ORDER = ["critical", "major", "minor"];

function headline(issue: Issue): string {
  const text = issue.description.split(" — ")[0].replace("Unsupported statement: ", "");
  return text.length > 96 ? text.slice(0, 95) + "…" : text;
}

const pretty = (key: string) =>
  key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()).replace("Prisma", "PRISMA").replace("cohen", "Cohen");

function Listing({ section }: { section: Record<string, unknown> }) {
  return (
    <>
      {Object.entries(section)
        .filter(([key]) => key !== "note")
        .map(([key, value]) => (
          <div className="kv" key={key}>
            <span>{pretty(key)}</span>
            <b className="num">{String(value)}</b>
          </div>
        ))}
    </>
  );
}

function Audit({ run }: { run: Run }) {
  const { data } = useSWR<AuditEvent[]>(`/api/runs/${run.id}/audit`, fetcher);
  const [agent, setAgent] = useState("");
  if (!data) return <div className="skeleton" style={{ height: 200 }} />;
  const agents = Array.from(new Set(data.map((e) => e.agent.split(":")[0]))).sort();
  const rows = agent ? data.filter((e) => e.agent.split(":")[0] === agent) : data;
  return (
    <>
      <div className="toolbar">
        <select className="input" style={{ width: 240 }} value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="">All agents</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {plural(rows.length, "event")} · full prompts and answers are in llm_trace.jsonl
        </span>
      </div>
      <div className="table-wrap" style={{ boxShadow: "none" }}>
        <div className="table-scroll" style={{ maxHeight: 440 }}>
          <table className="t">
            <thead>
              <tr>
                <th>#</th>
                <th>Time</th>
                <th>Agent</th>
                <th>Action</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={e.seq}>
                  <td className="muted num">{e.seq}</td>
                  <td className="muted num" style={{ whiteSpace: "nowrap" }}>{e.time}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{e.agent.replaceAll("_", " ")}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{e.action}</td>
                  <td className="mono muted" style={{ fontSize: 11.5, wordBreak: "break-word" }}>
                    {Object.entries(e.details).map(([k, v]) => `${k}: ${v}`).join(" · ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}

export function QualityTab({ run, onChange }: { run: Run; onChange: () => void }) {
  const { qa, evaluation } = run;
  const [auditOpen, setAuditOpen] = useState(false);
  const [computing, setComputing] = useState(false);

  async function compute() {
    setComputing(true);
    try {
      await post(`/api/runs/${run.id}/evaluate`);
      onChange();
    } finally {
      setComputing(false);
    }
  }

  const checks = qa?.checks ?? {};
  const quotes = checks.extraction_quotes ?? {};
  const rounds = checks.round ?? 1;
  const issues = qa ? [...qa.issues].sort((a, b) => ORDER.indexOf(a.severity) - ORDER.indexOf(b.severity)) : [];
  const serious = issues.filter((i) => i.severity !== "minor").length;

  return (
    <div className="stack">
      {!qa && <Empty>The Critic agent reviews the manuscript once a draft exists.</Empty>}
      {qa && (
        <>
          <div className="grid c4">
            <Stat label="Open issues" value={issues.length} lead note={`${serious} major · after ${plural(rounds, "critic round")}`} />
            <Stat label="Quotations found" value={quotes.verification_rate != null ? `${Math.round(quotes.verification_rate * 100)}%` : "—"}
                  note={`${quotes.quotes_verified ?? 0} of ${quotes.quotes_checked ?? 0} in the sources`} />
            <Stat label="PRISMA items" value={`${checks.prisma_items_reported ?? "—"}/${checks.prisma_items_total ?? "—"}`} note="reported" />
            <Stat label="Invented citations" value={(checks.unknown_citations ?? []).length} note="references to unknown records" />
          </div>

          {!issues.length && <Empty>The critic found no issue.</Empty>}
          <div className="stack" style={{ gap: 8 }}>
            {issues.map((issue, i) => (
              <Disclosure
                key={i}
                flat
                icon={
                  <span className={`issue-sev ${issue.severity}`} title={issue.severity}>
                    {issue.severity === "minor" ? <Info size={13} /> : <TriangleAlert size={13} />}
                  </span>
                }
                title={headline(issue)}
                extra={issue.area.split(":").pop()}
              >
                <p style={{ color: "var(--ink-2)" }}>{issue.description}</p>
                {issue.suggested_fix && (
                  <>
                    <div className="h5">Suggested fix</div>
                    <p style={{ color: "var(--ink-2)" }}>{issue.suggested_fix}</p>
                  </>
                )}
              </Disclosure>
            ))}
          </div>
        </>
      )}

      {(evaluation || run.status.state === "finished") && (
        <Disclosure icon={<ChartNoAxesColumn size={16} />} title="Evaluation" extra="completeness · accuracy · consistency · time">
          {!evaluation ? (
            <button className="btn primary" disabled={computing} onClick={compute}>
              Compute the evaluation
            </button>
          ) : (
            <>
              <div className="grid c2">
                <div className="stack">
                  <Card title="Completeness">
                    <Listing section={evaluation.completeness} />
                  </Card>
                  <Card title="Inter-agent consistency">
                    <Listing section={evaluation.consistency} />
                  </Card>
                </div>
                <div className="stack">
                  <Card title="Accuracy and grounding">
                    <Listing section={evaluation.accuracy} />
                  </Card>
                  <Card
                    title="Machine time per stage"
                    extra={`${evaluation.time.pipeline_hours.toFixed(1)} h · about ${Math.round(evaluation.time.manual_person_hours_estimate)} person-hours by hand`}
                  >
                    <Bars rows={run.timings.map((t) => ({ name: t.name, value: t.minutes, label: `${t.minutes}′` }))} />
                  </Card>
                </div>
              </div>
              <p className="hint" style={{ marginTop: 12 }}>{evaluation.time.note}</p>
            </>
          )}
        </Disclosure>
      )}

      {run.audit_events > 0 && (
        <Disclosure icon={<History size={16} />} title="Audit trail" extra={plural(run.audit_events, "event")} onOpen={() => setAuditOpen(true)}>
          {auditOpen && <Audit run={run} />}
        </Disclosure>
      )}
    </div>
  );
}
