"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSWRConfig } from "swr";
import { ArrowRight, LoaderCircle } from "lucide-react";
import { post } from "@/lib/api";

export function NewReview({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const [question, setQuestion] = useState("");
  const [auto, setAuto] = useState(false);
  const [perSource, setPerSource] = useState(60);
  const [screened, setScreened] = useState(50);
  const [rounds, setRounds] = useState(2);
  const [fallback, setFallback] = useState("abstract");
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function start() {
    setBusy(true);
    setError("");
    try {
      const { id } = await post("/api/runs", {
        question: question.trim(),
        auto,
        max_per_source: perSource,
        max_screen: screened,
        qa_rounds: rounds,
        fulltext_fallback: fallback,
      });
      await mutate("/api/runs");
      onClose();
      router.push(`/runs/${id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="New review">
        <h2>New review</h2>
        <p className="modal-sub">One research question is enough. You approve the protocol before anything is searched.</p>

        <label className="field-label" htmlFor="question">
          Research question
        </label>
        <textarea
          id="question"
          className="input"
          autoFocus
          rows={3}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. Does remote monitoring reduce readmissions in adults with heart failure?"
        />

        <div className="switch-row" onClick={() => setAuto(!auto)} role="switch" aria-checked={auto} tabIndex={0}
             onKeyDown={(e) => (e.key === " " || e.key === "Enter") && setAuto(!auto)}>
          <div className={`switch${auto ? " on" : ""}`} />
          <div>
            <div style={{ fontWeight: 560, fontSize: 13.5 }}>Autonomous mode</div>
            <div className="hint" style={{ marginTop: 1 }}>
              Skip the three human checkpoints. The report will say that no human verified it.
            </div>
          </div>
        </div>

        <button className="btn ghost sm" style={{ marginTop: 12, marginLeft: -6 }} onClick={() => setMore(!more)}>
          {more ? "Hide options" : "More options"}
        </button>
        {more && (
          <div style={{ marginTop: 8 }}>
            <div className="two">
              <div>
                <label className="field-label">Records per database</label>
                <input className="input num" type="number" min={10} max={2000} step={10} value={perSource}
                       onChange={(e) => setPerSource(Number(e.target.value))} />
              </div>
              <div>
                <label className="field-label">Records screened</label>
                <input className="input num" type="number" min={5} max={2000} step={5} value={screened}
                       onChange={(e) => setScreened(Number(e.target.value))} />
              </div>
              <div>
                <label className="field-label">Revision rounds</label>
                <select className="input" value={rounds} onChange={(e) => setRounds(Number(e.target.value))}>
                  {[0, 1, 2, 3].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="field-label">If no open full text</label>
                <select className="input" value={fallback} onChange={(e) => setFallback(e.target.value)}>
                  <option value="abstract">Assess on the abstract</option>
                  <option value="exclude">Report as not retrieved</option>
                </select>
              </div>
            </div>
            <p className="hint">On the free tier, 24 records screened and 1 revision round fit in one day of quota.</p>
          </div>
        )}

        {error && (
          <div className="alert error" style={{ marginTop: 16, marginBottom: 0 }}>
            {error}
          </div>
        )}

        <div className="modal-foot">
          <button className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="btn primary" disabled={busy || question.trim().length < 8} onClick={start}>
            {busy ? <LoaderCircle size={15} className="spin" /> : null}
            Start review {!busy && <ArrowRight size={15} />}
          </button>
        </div>
      </div>
    </div>
  );
}
