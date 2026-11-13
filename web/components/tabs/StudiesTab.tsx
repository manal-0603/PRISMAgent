import { ChevronRight, ExternalLink } from "lucide-react";
import type { Run, Study } from "@/lib/api";
import { Empty, Pill, ROB } from "../ui";

function StudyCard({ study }: { study: Study }) {
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
            {rob && <Pill tone={ROB[rob.overall]?.tone ?? ""}>Risk of bias: {rob.overall}</Pill>}
            {quotes.checked > 0 && (
              <Pill tone={quotes.verified === quotes.checked ? "good" : "warn"}>
                {quotes.verified}/{quotes.checked} quotations found
              </Pill>
            )}
            {study.basis === "abstract" && <span className="tag">abstract only</span>}
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
                source <ExternalLink size={11} style={{ verticalAlign: "-1px" }} />
              </a>
            </>
          )}
        </div>

        {study.findings.length > 0 && (
          <>
            <div className="h5">Key findings</div>
            <ul className="clean">
              {study.findings.map((f, i) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          </>
        )}

        <div className="h5">Extracted data</div>
        {study.items.map((item) => (
          <div className="item" key={item.field}>
            <div className="field">{item.field}</div>
            <div>
              {item.value}
              {item.quote && (
                <div className={`quote ${item.verified ? "ok" : "no"}`}>
                  “{item.quote}”
                  <em style={{ color: item.verified ? "var(--good)" : "var(--warn)" }}>{item.verified ? "found in source" : "not found as written"}</em>
                </div>
              )}
            </div>
          </div>
        ))}

        {rob && (
          <>
            <div className="h5">Risk of bias · {rob.tool}</div>
            <p style={{ fontSize: 13.5, color: "var(--ink-2)", marginBottom: 8 }}>{rob.why}</p>
            {rob.domains.map((d) => (
              <div className="item" key={d.domain}>
                <div className="field">{d.domain}</div>
                <div>
                  <Pill tone={ROB[d.judgement]?.tone ?? ""}>{d.judgement}</Pill>
                  <div className="muted" style={{ marginTop: 4 }}>{d.why}</div>
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
  if (!run.studies.length) return <Empty>No study has been extracted yet.</Empty>;
  return (
    <div className="stack" style={{ gap: 10 }}>
      {run.studies.map((study) => (
        <StudyCard key={study.rid} study={study} />
      ))}
    </div>
  );
}
