"use client";

import { Fragment, useState } from "react";
import { kappa, type Decision, type Run } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { DecisionPill, Empty, Stat } from "../ui";

const FILTERS = [
  { key: "all", label: "sc.all", test: (_: Decision) => true },
  { key: "include", label: "sc.included", test: (d: Decision) => d.final === "include" },
  { key: "exclude", label: "sc.excluded", test: (d: Decision) => d.final === "exclude" },
  { key: "conflict", label: "sc.conflicts", test: (d: Decision) => d.resolved_by !== "consensus" },
] as const;

export function ScreeningTab({ run }: { run: Run }) {
  const { t, n, v } = useI18n();
  const stages = [
    { key: "title_abstract" as const, label: t("sc.ta") },
    { key: "full_text" as const, label: t("sc.ft") },
  ].filter((s) => run.screening[s.key].length);
  const [stage, setStage] = useState<"title_abstract" | "full_text">("title_abstract");
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const [open, setOpen] = useState<string | null>(null);

  if (!stages.length) return <Empty>{t("sc.empty")}</Empty>;
  const current = stages.some((s) => s.key === stage) ? stage : stages[0].key;
  const decisions = run.screening[current];
  const agreement = run.agreement[current];
  const included = decisions.filter((d) => d.final === "include").length;
  const rows = decisions.filter(FILTERS.find((f) => f.key === filter)!.test);
  const who = (resolvedBy: string) => (resolvedBy === "human" ? t("who.human") : t("who.adjudicator"));

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
              {t(f.label)} <span className="num muted">{decisions.filter(f.test).length}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="grid c4">
        <Stat label={t("sc.assessed")} value={decisions.length} />
        <Stat label={t("sc.included")} value={included} lead />
        <Stat label={t("sc.excluded")} value={decisions.length - included} />
        <Stat label={t("ov.agreement")} value={kappa(agreement)} unit="κ"
              note={agreement ? t("sc.settled", { conflicts: n("disagreement", agreement.conflicts) }) : undefined} />
      </div>

      <div className="table-wrap">
        <div className="table-scroll">
          <table className="t">
            <thead>
              <tr>
                <th style={{ width: 70 }}>ID</th>
                <th>{t("sc.record")}</th>
                <th className="fit">{t("sc.decision")}</th>
                <th className="fit">{t("sc.reviewerA")}</th>
                <th className="fit">{t("sc.reviewerB")}</th>
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
                    <td className="muted fit">{v(d.a)}</td>
                    <td className="muted fit">{v(d.b)}</td>
                  </tr>
                  {open === d.rid && (
                    <tr className="detail">
                      <td />
                      <td colSpan={4}>
                        <div className="why">
                          <div className="wide">
                            <b>
                              {t("sc.decision")} · {d.resolved_by === "consensus" ? t("sc.agreed") : t("sc.settledBy", { who: who(d.resolved_by) })}
                            </b>
                            {d.why || "—"}
                            {d.reason && (
                              <div className="muted" style={{ marginTop: 4 }}>
                                {t("sc.reason", { reason: d.reason })}
                              </div>
                            )}
                          </div>
                          <div>
                            <b>
                              {t("sc.reviewerA")} · {v(d.a)}
                            </b>
                            {d.a_why || "—"}
                          </div>
                          <div>
                            <b>
                              {t("sc.reviewerB")} · {v(d.b)}
                            </b>
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
                    {t("sc.none")}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      <p className="hint" style={{ marginTop: -6 }}>
        {t("sc.hint")}
      </p>
    </div>
  );
}
