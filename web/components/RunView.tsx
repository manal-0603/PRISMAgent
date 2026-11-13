"use client";

import { useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { BookOpen, ClipboardList, FileText, Filter, Hourglass, LayoutDashboard, LoaderCircle, Play, ShieldCheck } from "lucide-react";
import { fetcher, post, type Run } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Pipeline } from "./Pipeline";
import { Checkpoint } from "./Checkpoint";
import { Overview } from "./tabs/Overview";
import { ProtocolTab } from "./tabs/ProtocolTab";
import { ScreeningTab } from "./tabs/ScreeningTab";
import { StudiesTab } from "./tabs/StudiesTab";
import { ReportTab } from "./tabs/ReportTab";
import { QualityTab } from "./tabs/QualityTab";

const TABS = [
  { key: "overview", icon: LayoutDashboard },
  { key: "protocol", icon: ClipboardList },
  { key: "screening", icon: Filter },
  { key: "studies", icon: BookOpen },
  { key: "report", icon: FileText },
  { key: "quality", icon: ShieldCheck },
] as const;

type TabKey = (typeof TABS)[number]["key"];

// The tab a human needs when a checkpoint is waiting.
const STAGE_KEYS = {
  protocol: 1, search_strategy: 1, retrieval: 1, screen_title_abstract: 1, screen_full_text: 1,
  extraction: 1, synthesis: 1, critic: 1, finalize: 1,
} as const;

const CHECKPOINT_TAB: Record<string, TabKey> = { protocol: "protocol", screening: "screening", report: "quality" };

export function RunView({ id }: { id: string }) {
  const { mutate: mutateAll } = useSWRConfig();
  const { t, date } = useI18n();
  const { data: run, error, mutate } = useSWR<Run>(`/api/runs/${id}`, fetcher, {
    refreshInterval: (latest) => (latest?.status.state === "running" ? 2500 : 0),
  });
  const [chosen, setChosen] = useState<TabKey | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");

  if (error) {
    return (
      <div className="welcome">
        <h1>{t("head.cannotOpen")}</h1>
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
  // The state and the current stage come from the API as keys; the wording is the interface's.
  const stageKey = `stage.${status.current}` as Parameters<typeof t>[0];
  const statusLabel =
    status.state === "running"
      ? status.current && status.current in STAGE_KEYS
        ? t(stageKey)
        : t("status.starting")
      : t(`status.${status.state}`);
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
              {statusLabel}
            </span>
            {status.elsewhere && <span className="state">{t("status.elsewhere")}</span>}
            {status.waiting_for_quota && (
              <span className="state">
                <Hourglass size={12} /> {t("status.quota")}
              </span>
            )}
          </div>
          <h1 className="title">{run.question}</h1>
          <div className="meta">
            <span>{t("head.started", { date: date(run.created, true) })}</span>
            <span>{run.options.auto_approve ? t("head.auto") : t("head.human")}</span>
            <span>{t("head.cap", { n: run.options.max_screen })}</span>
          </div>
        </div>
        {(status.state === "paused" || status.state === "error") && (
          <button className="btn primary" disabled={busy} onClick={() => advance()}>
            <Play size={14} /> {t("head.resume")}
          </button>
        )}
      </header>

      {status.error && <div className="alert error">{status.error}</div>}
      {actionError && <div className="alert error">{actionError}</div>}
      {status.state === "paused" && (
        <div className="alert note">{t("head.pausedNote")}</div>
      )}

      <Pipeline steps={status.steps} running={status.state === "running"} />

      {run.pending && <Checkpoint run={run} busy={busy} onDecision={advance} />}

      <div className="tabs" role="tablist">
        {TABS.map(({ key, icon: Icon }) => (
          <button key={key} role="tab" aria-selected={tab === key} className="tab" onClick={() => setChosen(key)}>
            <Icon size={15} />
            {t(`tab.${key}`)}
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
