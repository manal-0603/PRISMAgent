"use client";

import { createContext, useCallback, useContext, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import { FileSearch, Plus } from "lucide-react";
import { fetcher, formatDate, type Quota, type RunSummary } from "@/lib/api";
import { NewReview } from "./NewReview";

const NewReviewContext = createContext<() => void>(() => {});
export const useNewReview = () => useContext(NewReviewContext);

const STATE_LABEL: Record<string, string> = {
  running: "Running",
  waiting: "Waiting for you",
  finished: "Finished",
  error: "Stopped",
  paused: "Not finished",
};

export function Shell({ children }: { children: React.ReactNode }) {
  const [creating, setCreating] = useState(false);
  const open = useCallback(() => setCreating(true), []);
  const params = useParams<{ id?: string }>();
  const { data: runs } = useSWR<RunSummary[]>("/api/runs", fetcher, {
    refreshInterval: (latest) => (latest?.some((r) => r.state === "running") ? 4000 : 20000),
  });
  const { data: quota } = useSWR<Quota[]>("/api/quota", fetcher, { refreshInterval: 60000 });

  return (
    <NewReviewContext.Provider value={open}>
      <div className="shell">
        <aside className="side">
          <Link href="/" className="brand" style={{ textDecoration: "none", color: "inherit" }}>
            <div className="brand-mark">
              <FileSearch size={18} />
            </div>
            <div>
              <div className="brand-name">PRISMAgent</div>
              <div className="brand-sub">Systematic reviews, by agents</div>
            </div>
          </Link>

          <button className="side-new" onClick={open}>
            <Plus size={16} /> New review
          </button>

          <div className="side-list">
            <div className="side-label">Reviews</div>
            {runs?.map((run) => (
              <Link key={run.id} href={`/runs/${run.id}`} className={`run-link${params?.id === run.id ? " active" : ""}`}>
                <div className="run-q">{run.question}</div>
                <div className="run-meta">
                  <span className={`dot ${run.state}`} />
                  <span>
                    {STATE_LABEL[run.state]}
                    {run.included !== null ? ` · ${run.included} studies` : ""}
                  </span>
                  <span style={{ marginLeft: "auto" }}>{formatDate(run.created)}</span>
                </div>
              </Link>
            ))}
            {runs && !runs.length && <div className="run-meta" style={{ padding: "0 8px" }}>No review yet</div>}
          </div>

          {quota && (
            <div className="quota" title="Estimate of the free daily allowance left for each model (it refills continuously).">
              <div className="side-label" style={{ padding: 0, marginBottom: 2 }}>
                Free quota left
              </div>
              {quota.map((q) => {
                const share = Math.max(0, Math.min(1, q.available / q.per_day));
                return (
                  <div className="quota-row" key={q.model}>
                    <span>{q.short}</span>
                    <div className="quota-track">
                      <div className={`quota-fill${share < 0.15 ? " low" : share < 0.4 ? " mid" : ""}`} style={{ width: `${share * 100}%` }} />
                    </div>
                    <span className="num" style={{ textAlign: "right" }}>
                      {Math.round(share * 100)}%
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </aside>

        <main className="main">
          <div className="page">{children}</div>
        </main>
      </div>
      {creating && <NewReview onClose={() => setCreating(false)} />}
    </NewReviewContext.Provider>
  );
}
