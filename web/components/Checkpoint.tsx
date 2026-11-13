"use client";

import { useMemo, useState } from "react";
import { Check, UserCheck } from "lucide-react";
import type { Run } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type Props = { run: Run; busy: boolean; onDecision: (resume: Record<string, unknown>) => void };

export function Checkpoint(props: Props) {
  const kind = props.run.pending.checkpoint;
  if (kind === "protocol") return <ProtocolCheckpoint {...props} />;
  if (kind === "screening") return <ScreeningCheckpoint {...props} />;
  if (kind === "report") return <ReportCheckpoint {...props} />;
  return null;
}

function Head({ step, title, children }: { step: number; title: string; children: React.ReactNode }) {
  const { t } = useI18n();
  return (
    <div className="callout-head">
      <div className="callout-icon">
        <UserCheck size={17} />
      </div>
      <div>
        <h3>{t("cp.head", { n: step, title })}</h3>
        <p>{children}</p>
      </div>
    </div>
  );
}

function ProtocolCheckpoint({ run, busy, onDecision }: Props) {
  const { t } = useI18n();
  const [mode, setMode] = useState<"" | "changes" | "edit">("");
  const [feedback, setFeedback] = useState("");
  const [json, setJson] = useState(() => JSON.stringify(run.pending.protocol, null, 2));
  const [jsonError, setJsonError] = useState("");

  function saveEdits() {
    try {
      onDecision({ action: "approve", protocol: JSON.parse(json) });
    } catch (e) {
      setJsonError(t("cp1.invalid", { error: (e as Error).message }));
    }
  }

  return (
    <div className="callout">
      <Head step={1} title={t("cp1.title")}>
        {t("cp1.text")}
      </Head>
      <div className="callout-actions">
        <button className="btn primary" disabled={busy} onClick={() => onDecision({ action: "approve" })}>
          <Check size={15} /> {t("cp.approve")}
        </button>
        <button className="btn" disabled={busy} onClick={() => setMode(mode === "changes" ? "" : "changes")}>
          {t("cp1.changes")}
        </button>
        <button className="btn ghost" disabled={busy} onClick={() => setMode(mode === "edit" ? "" : "edit")}>
          {t("cp1.edit")}
        </button>
      </div>
      {mode === "changes" && (
        <div className="callout-body">
          <textarea className="input" autoFocus value={feedback} onChange={(e) => setFeedback(e.target.value)}
                    placeholder={t("cp1.changesPlaceholder")} />
          <div className="callout-actions">
            <button className="btn primary" disabled={busy || !feedback.trim()} onClick={() => onDecision({ action: "revise", feedback: feedback.trim() })}>
              {t("cp1.send")}
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
              {t("cp1.save")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

type PendingDecision = { rid: string; title: string; final: string; resolved_by: string; a: string; b: string; rationale: string };

function ScreeningCheckpoint({ run, busy, onDecision }: Props) {
  const { t, n, v } = useI18n();
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
      <Head step={2} title={t("cp2.title")}>
        {t("cp2.text", { n: decisions.length })}
      </Head>
      <div className="callout-body">
        <div className="toolbar">
          <div className="segmented sm">
            <button aria-pressed={!all} onClick={() => setAll(false)}>
              {t("cp2.disputed", { n: decisions.filter((d) => d.final === "include" || d.resolved_by !== "consensus").length })}
            </button>
            <button aria-pressed={all} onClick={() => setAll(true)}>
              {t("cp2.all", { n: decisions.length })}
            </button>
          </div>
        </div>
        <div className="table-wrap">
          <div className="table-scroll" style={{ maxHeight: 380 }}>
            <table className="t">
              <thead>
                <tr>
                  <th>{t("sc.record")}</th>
                  <th className="fit">{t("cp2.reviewers")}</th>
                  <th className="fit">{t("sc.decision")}</th>
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
                        {v(d.a)} / {v(d.b)}
                        {d.resolved_by !== "consensus" && (
                          <div style={{ fontSize: 12 }}>
                            {t("cp2.settledBy", { who: d.resolved_by === "human" ? t("who.human") : t("who.adjudicator") })}
                          </div>
                        )}
                      </td>
                      <td className="fit">
                        <div className="segmented sm">
                          <button aria-pressed={value === "include"} onClick={() => set(d.rid, d.final, "include")}>
                            {t("cp2.include")}
                          </button>
                          <button aria-pressed={value === "exclude"} onClick={() => set(d.rid, d.final, "exclude")}>
                            {t("cp2.exclude")}
                          </button>
                        </div>
                        {overrides[d.rid] && <div className="hint" style={{ color: "var(--warn)" }}>{t("cp2.changed")}</div>}
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
          <Check size={15} /> {changed ? t("cp2.approveWith", { changes: n("change", changed) }) : t("cp.approve")}
        </button>
      </div>
    </div>
  );
}

function ReportCheckpoint({ run, busy, onDecision }: Props) {
  const { t, n } = useI18n();
  const [revising, setRevising] = useState(false);
  const [feedback, setFeedback] = useState("");
  const issues = run.pending.qa_report?.issues?.length ?? 0;

  return (
    <div className="callout">
      <Head step={3} title={t("cp3.title")}>
        {issues ? t("cp3.issues", { issues: n("issue", issues) }) : t("cp3.clean")} {t("cp3.then")}
      </Head>
      <div className="callout-actions">
        <button className="btn primary" disabled={busy} onClick={() => onDecision({ action: "approve" })}>
          <Check size={15} /> {t("cp3.approve")}
        </button>
        <button className="btn" disabled={busy} onClick={() => setRevising(!revising)}>
          {t("cp3.revise")}
        </button>
      </div>
      {revising && (
        <div className="callout-body">
          <textarea className="input" autoFocus value={feedback} onChange={(e) => setFeedback(e.target.value)}
                    placeholder={t("cp3.placeholder")} />
          <div className="callout-actions">
            <button className="btn primary" disabled={busy || !feedback.trim()} onClick={() => onDecision({ action: "revise", feedback: feedback.trim() })}>
              {t("cp3.send")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
