// Small presentational pieces shared by the tabs.

import { ChevronRight } from "lucide-react";

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

export const ROB: Record<string, { color: string; label: string; tone: string }> = {
  low: { color: "#2fa56f", label: "Low", tone: "good" },
  "some concerns": { color: "#e6a52e", label: "Some concerns", tone: "warn" },
  high: { color: "#d2453c", label: "High", tone: "crit" },
  unclear: { color: "#b9b6ab", label: "Unclear", tone: "" },
};

export function RobBar({ levels }: { levels: string[] }) {
  const counts = Object.keys(ROB).map((k) => ({ k, n: levels.filter((l) => l === k).length }));
  return (
    <>
      <div className="seg">
        {counts.filter((c) => c.n).map((c) => (
          <span key={c.k} style={{ flex: c.n, background: ROB[c.k].color }} title={`${ROB[c.k].label}: ${c.n}`} />
        ))}
      </div>
      <div className="legend">
        {counts.filter((c) => c.n).map((c) => (
          <span key={c.k}>
            <i style={{ background: ROB[c.k].color }} />
            {ROB[c.k].label} <b className="num">{c.n}</b>
          </span>
        ))}
      </div>
    </>
  );
}

export function DecisionPill({ value }: { value: string }) {
  const tone = value === "include" ? "good" : value === "exclude" ? "" : "warn";
  return <Pill tone={tone}>{value}</Pill>;
}
