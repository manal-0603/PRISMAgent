"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { BookOpen, ClipboardList, FileText, Filter, Hourglass, LayoutDashboard, LoaderCircle, Play, ShieldCheck } from "lucide-react";
import { fetcher, formatDate, post, type Run } from "@/lib/api";
import { Pipeline } from "./Pipeline";
import { Checkpoint } from "./Checkpoint";
import { Overview } from "./tabs/Overview";
import { ProtocolTab } from "./tabs/ProtocolTab";
import { ScreeningTab } from "./tabs/ScreeningTab";
import { StudiesTab } from "./tabs/StudiesTab";
import { ReportTab } from "./tabs/ReportTab";
import { QualityTab } from "./tabs/QualityTab";

const TABS = [
  { key: "overview", label: "Overview", icon: LayoutDashboard },
  { key: "protocol", label: "Protocol", icon: ClipboardList },
  { key: "screening", label: "Screening", icon: Filter },
  { key: "studies", label: "Studies", icon: BookOpen },
  { key: "report", label: "Report", icon: FileText },
  { key: "quality", label: "Quality", icon: ShieldCheck },
] as const;

type TabKey = (typeof TABS)[number]["key"];

// The tab a human needs when a checkpoint is waiting.
const CHECKPOINT_TAB: Record<string, TabKey> = { protocol: "protocol", screening: "screening", report: "quality" };

export function RunView({ id }: { id: string }) {
  const { mutate: mutateAll } = useSWRConfig();
  const { data: run, error, mutate } = useSWR<Run>(`/api/runs/${id}`, fetcher, {
    refreshInterval: (latest) => (latest?.status.state === "running" ? 2500 : 0),
  });
  const [chosen, setChosen] = useState<TabKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  if (error) {
    return (
      <div className="welcome">
        <h1>This review cannot be opened</h1>
        <p>{error.message}</p>
      </div>
    );
  }
  if (!run) {
    return (
      <div className="stack">
        <div className="skeleton" style={{ height: 96 }} />
        <div className="skeleton" style={{ height: 86 }} />
        <div className="skeleton" style={{ height: 320 }} />
      </div>
    );
  }

  async function advance(resume?: Record<string, unknown>) {
    setBusy(true);
    setActionError("");
    try {
      await post(`/api/runs/${id}/advance`, resume ? { resume } : {});
      await Promise.all([mutate(), mutateAll("/api/runs")]);
    } catch (e) {
      setActionError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const { status } = run;
  const tab: TabKey = chosen ?? (run.pending ? CHECKPOINT_TAB[run.pending.checkpoint] ?? "overview" : "overview");
  const issues = run.qa?.issues.length ?? 0;
  const counts: Partial<Record<TabKey, number>> = { studies: run.studies.length || undefined, quality: issues || undefined };

  return (
    <>
      <header className="head">
        <div>
          <div className="eyebrow">
            <span className={`state ${status.state}`}>
              {status.state === "running" && <LoaderCircle size={13} className="spin" />}
              {status.state !== "running" && <span className={`dot ${status.state}`} />}
              {status.label}
            </span>
            {status.elsewhere && <span className="state">running in another window</span>}
            {status.waiting_for_quota && (
              <span className="state">
                <Hourglass size={12} /> waiting for the model quota
              </span>
            )}
          </div>
          <h1 className="title">{run.question}</h1>
          <div className="meta">
            <span>Started {formatDate(run.created, true)}</span>
            <span>{run.options.auto_approve ? "Autonomous" : "Human-in-the-loop"}</span>
            <span>up to {run.options.max_screen} records screened</span>
          </div>
        </div>
        {(status.state === "paused" || status.state === "error") && (
          <button className="btn primary" disabled={busy} onClick={() => advance()}>
            <Play size={14} /> Resume
          </button>
        )}
      </header>

      {status.error && <div className="alert error">{status.error}</div>}
      {actionError && <div className="alert error">{actionError}</div>}
      {status.state === "paused" && (
        <div className="alert note">This review stopped before the end. Resume continues from the last completed stage.</div>
      )}

      <Pipeline steps={status.steps} running={status.state === "running"} />

      {run.pending && <Checkpoint run={run} busy={busy} onDecision={advance} />}

      <div className="tabs" role="tablist">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} role="tab" aria-selected={tab === key} className="tab" onClick={() => setChosen(key)}>
            <Icon size={15} />
            {label}
            {counts[key] !== undefined && <span className={`count${key === "quality" ? " warn" : ""}`}>{counts[key]}</span>}
          </button>
        ))}
      </div>

      <div role="tabpanel">
        {tab === "overview" && <Overview run={run} />}
        {tab === "protocol" && <ProtocolTab run={run} />}
        {tab === "screening" && <ScreeningTab run={run} />}
        {tab === "studies" && <StudiesTab run={run} />}
        {tab === "report" && <ReportTab run={run} />}
        {tab === "quality" && <QualityTab run={run} onChange={() => mutate()} />}
      </div>
    </>
  );
}
