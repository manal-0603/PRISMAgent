"use client";

import { Fragment, useState } from "react";
import { kappa, plural, type Decision, type Run } from "@/lib/api";
import { DecisionPill, Empty, Stat } from "../ui";

const FILTERS = [
  { key: "all", label: "All", test: (_: Decision) => true },
  { key: "include", label: "Included", test: (d: Decision) => d.final === "include" },
  { key: "exclude", label: "Excluded", test: (d: Decision) => d.final === "exclude" },
  { key: "conflict", label: "Disagreements", test: (d: Decision) => d.resolved_by !== "consensus" },
] as const;

export function ScreeningTab({ run }: { run: Run }) {
  const stages = [
    { key: "title_abstract" as const, label: "Title and abstract" },
    { key: "full_text" as const, label: "Full text" },
  ].filter((s) => run.screening[s.key].length);
  const [stage, setStage] = useState<"title_abstract" | "full_text">("title_abstract");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [open, setOpen] = useState<string | null>(null);

  if (!stages.length) return <Empty>No screening decision yet.</Empty>;
  const current = stages.some((s) => s.key === stage) ? stage : stages[0].key;
  const decisions = run.screening[current];
  const agreement = run.agreement[current];
  const included = decisions.filter((d) => d.final === "include").length;
  const rows = decisions.filter(FILTERS.find((f) => f.key === filter)!.test);

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <div className="segmented">
          {stages.map((s) => (
            <button key={s.key} aria-pressed={current === s.key} onClick={() => (setStage(s.key), setOpen(null))}>
              {s.label}
            </button>
          ))}
        </div>
        <div className="segmented sm">
          {FILTERS.map((f) => (
            <button key={f.key} aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
              {f.label} <span className="num muted">{decisions.filter(f.test).length}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid c4">
        <Stat label="Assessed" value={decisions.length} />
        <Stat label="Included" value={included} lead />
        <Stat label="Excluded" value={decisions.length - included} />
        <Stat label="Reviewer agreement" value={kappa(agreement)} unit="κ"
              note={agreement ? `${plural(agreement.conflicts, "disagreement")} settled` : undefined} />
      </div>

      <div className="table-wrap">
        <div className="table-scroll">
          <table className="t">
            <thead>
              <tr>
                <th style={{ width: 70 }}>ID</th>
                <th>Record</th>
                <th className="fit">Decision</th>
                <th className="fit">Reviewer A</th>
                <th className="fit">Reviewer B</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <Fragment key={d.rid}>
                  <tr className={`click${open === d.rid ? " open" : ""}`} onClick={() => setOpen(open === d.rid ? null : d.rid)}>
                    <td className="muted num">{d.rid}</td>
                    <td style={{ fontWeight: 520 }}>{d.title}</td>
                    <td className="fit">
                      <DecisionPill value={d.final} />
                    </td>
                    <td className="muted fit">{d.a}</td>
                    <td className="muted fit">{d.b}</td>
                  </tr>
                  {open === d.rid && (
                    <tr className="detail">
                      <td />
                      <td colSpan={4}>
                        <div className="why">
                          <div className="wide">
                            <b>
                              Decision · {d.resolved_by === "consensus" ? "both reviewers agreed" : `settled by the ${d.resolved_by}`}
                            </b>
                            {d.why || "—"}
                            {d.reason && <div className="muted" style={{ marginTop: 4 }}>Reason: {d.reason}</div>}
                          </div>
                          <div>
                            <b>Reviewer A · {d.a}</b>
                            {d.a_why || "—"}
                          </div>
                          <div>
                            <b>Reviewer B · {d.b}</b>
                            {d.b_why || "—"}
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
              {!rows.length && (
                <tr>
                  <td colSpan={5} className="muted" style={{ textAlign: "center", padding: 28 }}>
                    No record in this view.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <p className="hint" style={{ marginTop: -6 }}>Click a record to read why it was included or excluded.</p>
    </div>
  );
}
