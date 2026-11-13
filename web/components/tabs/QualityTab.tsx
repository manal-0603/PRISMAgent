"use client";

import { useState } from "react";
import useSWR from "swr";
import { ChartNoAxesColumn, History, Info, TriangleAlert } from "lucide-react";
import { fetcher, post, type AuditEvent, type Issue, type Run } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Bars, Card, Disclosure, Empty, Stat } from "../ui";

const ORDER = ["critical", "major", "minor"];

function headline(issue: Issue): string {
  const text = issue.description.split(" — ")[0].replace("Unsupported statement: ", "");
  return text.length > 96 ? text.slice(0, 95) + "…" : text;
}

function Listing({ section }: { section: Record<string, unknown> }) {
  const { measure, v } = useI18n();
  return (
    <>
      {Object.entries(section)
        .filter(([key]) => key !== "note")
        .map(([key, value]) => (
          <div className="kv" key={key}>
            <span>{measure(key)}</span>
            <b className="num">{v(String(value))}</b>
          </div>
        ))}
    </>
  );
}

function Audit({ run }: { run: Run }) {
  const { t, n } = useI18n();
  const { data } = useSWR<AuditEvent[]>(`/api/runs/${run.id}/audit`, fetcher);
  const [agent, setAgent] = useState("");
  if (!data) return <div className="skeleton" style={{ height: 200 }} />;
  const agents = Array.from(new Set(data.map((e) => e.agent.split(":")[0]))).sort();
  const rows = agent ? data.filter((e) => e.agent.split(":")[0] === agent) : data;
  return (
    <>
      <div className="toolbar">
        <select className="input" style={{ width: 240 }} value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="">{t("qa.allAgents")}</option>
          {agents.map((a) => (
            <option key={a} value={a}>
              {a.replaceAll("_", " ")}
            </option>
          ))}
        </select>
        <span className="muted" style={{ fontSize: 12.5 }}>
          {n("event", rows.length)} · {t("qa.trace")}
        </span>
      </div>
      <div className="table-wrap" style={{ boxShadow: "none" }}>
        <div className="table-scroll" style={{ maxHeight: 440 }}>
          <table className="t">
            <thead>
              <tr>
                <th>#</th>
                <th>{t("qa.colTime")}</th>
                <th>{t("qa.colAgent")}</th>
                <th>{t("qa.colAction")}</th>
                <th>{t("qa.colDetails")}</th>
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
  const { t, n, v } = useI18n();
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
      {!qa && <Empty>{t("qa.empty")}</Empty>}
      {qa && (
        <>
          <div className="grid c4">
            <Stat label={t("qa.open")} value={issues.length} lead note={t("qa.openNote", { major: serious, rounds: n("round", rounds) })} />
            <Stat label={t("qa.quotes")} value={quotes.verification_rate != null ? `${Math.round(quotes.verification_rate * 100)}%` : "—"}
                  note={t("qa.quotesNote", { found: quotes.quotes_verified ?? 0, checked: quotes.quotes_checked ?? 0 })} />
            <Stat label={t("qa.prisma")} value={`${checks.prisma_items_reported ?? "—"}/${checks.prisma_items_total ?? "—"}`} note={t("qa.reported")} />
            <Stat label={t("qa.invented")} value={(checks.unknown_citations ?? []).length} note={t("qa.inventedNote")} />
          </div>

          {!issues.length && <Empty>{t("qa.none")}</Empty>}
          <div className="stack" style={{ gap: 8 }}>
            {issues.map((issue, i) => (
              <Disclosure
                key={i}
                flat
                icon={
                  <span className={`issue-sev ${issue.severity}`} title={v(issue.severity)}>
                    {issue.severity === "minor" ? <Info size={13} /> : <TriangleAlert size={13} />}
                  </span>
                }
                title={headline(issue)}
                extra={issue.area.split(":").pop()}
              >
                <p style={{ color: "var(--ink-2)" }}>{issue.description}</p>
                {issue.suggested_fix && (
                  <>
                    <div className="h5">{t("qa.fix")}</div>
                    <p style={{ color: "var(--ink-2)" }}>{issue.suggested_fix}</p>
                  </>
                )}
              </Disclosure>
            ))}
          </div>
        </>
      )}

      {(evaluation || run.status.state === "finished") && (
        <Disclosure icon={<ChartNoAxesColumn size={16} />} title={t("qa.evaluation")} extra={t("qa.evaluationExtra")}>
          {!evaluation ? (
            <button className="btn primary" disabled={computing} onClick={compute}>
              {t("qa.compute")}
            </button>
          ) : (
            <>
              <div className="grid c2">
                <div className="stack">
                  <Card title={t("qa.completeness")}>
                    <Listing section={evaluation.completeness} />
                  </Card>
                  <Card title={t("qa.consistency")}>
                    <Listing section={evaluation.consistency} />
                  </Card>
                </div>
                <div className="stack">
                  <Card title={t("qa.accuracy")}>
                    <Listing section={evaluation.accuracy} />
                  </Card>
                  <Card
                    title={t("qa.time")}
                    extra={t("qa.timeExtra", { hours: evaluation.time.pipeline_hours.toFixed(1), manual: Math.round(evaluation.time.manual_person_hours_estimate) })}
                  >
                    <Bars rows={run.timings.map((timing) => ({ name: t(`step.${timing.key}` as Parameters<typeof t>[0]), value: timing.minutes, label: `${timing.minutes}′` }))} />
                  </Card>
                </div>
              </div>
              <p className="hint" style={{ marginTop: 12 }}>{t("qa.timeNote")}</p>
            </>
          )}
        </Disclosure>
      )}

      {run.audit_events > 0 && (
        <Disclosure icon={<History size={16} />} title={t("qa.audit")} extra={n("event", run.audit_events)} onOpen={() => setAuditOpen(true)}>
          {auditOpen && <Audit run={run} />}
        </Disclosure>
      )}
    </div>
  );
}
