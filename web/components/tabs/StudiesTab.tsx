"use client";

import { ChevronRight, ExternalLink } from "lucide-react";
import type { Run, Study } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Empty, Pill, ROB } from "../ui";

function StudyCard({ study }: { study: Study }) {
  const { t, v } = useI18n();
  const { quotes, rob } = study;
  return (
    <details className="study">
      <summary>
        <div>
          <h4>{study.title}</h4>
          <div className="by">
            {study.ref}
            {study.venue && ` · ${study.venue}`}
          </div>
          <div className="badges" style={{ marginTop: 9 }}>
            {rob && <Pill tone={ROB[rob.overall]?.tone ?? ""}>{t("st.rob", { level: v(rob.overall) })}</Pill>}
            {quotes.checked > 0 && (
              <Pill tone={quotes.verified === quotes.checked ? "good" : "warn"}>
                {t("st.quotes", { found: quotes.verified, checked: quotes.checked })}
              </Pill>
            )}
            {study.basis === "abstract" && <span className="tag">{t("st.abstractOnly")}</span>}
          </div>
        </div>
        <ChevronRight size={17} className="chev" />
      </summary>
      <div className="study-body">
        <div className="muted" style={{ fontSize: 13, marginBottom: 14 }}>
          {[study.design, study.sample, study.rid].filter(Boolean).join(" · ")}
          {study.url && (
            <>
              {" · "}
              <a href={study.url} target="_blank" rel="noreferrer">
                {t("st.source")} <ExternalLink size={11} style={{ verticalAlign: "-1px" }} />
              </a>
            </>
          )}
        </div>

        {study.findings.length > 0 && (
          <>
            <div className="h5">{t("st.findings")}</div>
            <ul className="clean">
              {study.findings.map((finding, i) => (
                <li key={i}>{finding}</li>
              ))}
            </ul>
          </>
        )}

        <div className="h5">{t("st.data")}</div>
        {study.items.map((item) => (
          <div className="item" key={item.field}>
            <div className="field">{item.field}</div>
            <div>
              {item.value}
              {item.quote && (
                <div className={`quote ${item.verified ? "ok" : "no"}`}>
                  “{item.quote}”
                  <em style={{ color: item.verified ? "var(--good)" : "var(--warn)" }}>{item.verified ? t("st.found") : t("st.notFound")}</em>
                </div>
              )}
            </div>
          </div>
        ))}

        {rob && (
          <>
            <div className="h5">
              {t("ov.rob")} · {rob.tool}
            </div>
            <p style={{ fontSize: 13.5, color: "var(--ink-2)", marginBottom: 8 }}>{rob.why}</p>
            {rob.domains.map((d) => (
              <div className="item" key={d.domain}>
                <div className="field">{d.domain}</div>
                <div>
                  <Pill tone={ROB[d.judgement]?.tone ?? ""}>{v(d.judgement)}</Pill>
                  <div className="muted" style={{ marginTop: 4 }}>
                    {d.why}
                  </div>
                </div>
              </div>
            ))}
          </>
        )}
      </div>
    </details>
  );
}

export function StudiesTab({ run }: { run: Run }) {
  const { t } = useI18n();
  if (!run.studies.length) return <Empty>{t("st.empty")}</Empty>;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {run.studies.map((study) => (
        <StudyCard key={study.rid} study={study} />
      ))}
    </div>
  );
}
