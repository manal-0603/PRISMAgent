"use client";

// Small presentational pieces shared by the tabs.

import { ChevronRight } from "lucide-react";
import { useI18n } from "@/lib/i18n";

export function Stat({ label, value, unit, note, lead }: { label: string; value: React.ReactNode; unit?: string; note?: string; lead?: boolean }) {
  return (
    <div className={`stat${lead ? " lead" : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      {note && <div className="stat-note">{note}</div>}
    </div>
  );
}

export function Card({ title, extra, children }: { title?: string; extra?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="card">
      {title && (
        <h3 className="card-title">
          {title}
          {extra && <small>{extra}</small>}
        </h3>
      )}
      {children}
    </section>
  );
}

export function Pill({ tone = "", children }: { tone?: string; children: React.ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

export function Disclosure({
  icon,
  title,
  extra,
  children,
  flat,
  onOpen,
}: {
  icon?: React.ReactNode;
  title: React.ReactNode;
  extra?: React.ReactNode;
  children: React.ReactNode;
  flat?: boolean;
  onOpen?: () => void;
}) {
  return (
    <details className={`disc${flat ? " flat" : ""}`} onToggle={(e) => (e.currentTarget as HTMLDetailsElement).open && onOpen?.()}>
      <summary>
        {icon}
        <span className="sum-main">{title}</span>
        {extra && <span className="sum-extra">{extra}</span>}
        <ChevronRight size={16} className="chev" />
      </summary>
      <div className="disc-body">{children}</div>
    </details>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

export type Bar = { name: string; value: number; label?: string; tip?: string; key?: boolean };

export function Bars({ rows }: { rows: Bar[] }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="bars">
      {rows.map((r) => (
        <div key={r.name} className={`bar-row${r.key ? " key" : ""}`} title={r.tip}>
          <span className="name">{r.name}</span>
          <div className="bar-track">
            <div className="bar-fill" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
          <span className="val">{r.label ?? r.value}</span>
        </div>
      ))}
    </div>
  );
}

// Risk-of-bias levels as the pipeline writes them; their label comes from the interface language.
export const ROB: Record<string, { color: string; tone: string }> = {
  low: { color: "#2fa56f", tone: "good" },
  "some concerns": { color: "#e6a52e", tone: "warn" },
  high: { color: "#d2453c", tone: "crit" },
  unclear: { color: "#b9b6ab", tone: "" },
};

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

export function RobBar({ levels }: { levels: string[] }) {
  const { v } = useI18n();
  const counts = Object.keys(ROB).map((k) => ({ k, n: levels.filter((l) => l === k).length }));
  return (
    <>
      <div className="seg">
        {counts.filter((c) => c.n).map((c) => (
          <span key={c.k} style={{ flex: c.n, background: ROB[c.k].color }} title={`${capital(v(c.k))}: ${c.n}`} />
        ))}
      </div>
      <div className="legend">
        {counts.filter((c) => c.n).map((c) => (
          <span key={c.k}>
            <i style={{ background: ROB[c.k].color }} />
            {capital(v(c.k))} <b className="num">{c.n}</b>
          </span>
        ))}
      </div>
    </>
  );
}

export function DecisionPill({ value }: { value: string }) {
  const { v } = useI18n();
  const tone = value === "include" ? "good" : value === "exclude" ? "" : "warn";
  return <Pill tone={tone}>{v(value)}</Pill>;
}
