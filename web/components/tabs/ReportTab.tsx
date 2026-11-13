"use client";

import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download } from "lucide-react";
import { fetcher, fileUrl, type Run } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { Empty } from "../ui";

const DOWNLOADS = [
  { file: "report.docx", label: "Word" },
  { file: "report.md", label: "Markdown" },
  { file: "references.bib", label: "BibTeX" },
  { file: "evidence_table.csv", label: "" },
];

export function ReportTab({ run }: { run: Run }) {
  const { t, number } = useI18n();
  const { data, error } = useSWR<{ markdown: string }>(run.report ? `/api/runs/${run.id}/report?v=${run.report.words}` : null, fetcher);
  if (!run.report) return <Empty>{t("rp.empty")}</Empty>;

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <span className="muted" style={{ fontSize: 13 }}>
          {t("rp.words", { n: number(run.report.words) })} · {run.report.final ? t("rp.final") : t("rp.draft")}
          {t("rp.language") && <> · {t("rp.language")}</>}
        </span>
        <div className="badges">
          {DOWNLOADS.filter((d) => run.files.includes(d.file)).map((d) => (
            <a key={d.file} className="btn sm" href={fileUrl(run.id, d.file)} download>
              <Download size={13} /> {d.label || t("rp.evidence")}
            </a>
          ))}
        </div>
      </div>
      <article className="paper">
        {error && <p className="muted">{t("rp.failed")}</p>}
        {!data && !error && <div className="skeleton" style={{ height: 400 }} />}
        {data && (
          <div className="prose">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                // images of the report are files of the run folder
                img: ({ src, alt }) => {
                  const name = typeof src === "string" ? src : "";
                  // eslint-disable-next-line @next/next/no-img-element
                  return <img src={/^https?:/.test(name) ? name : fileUrl(run.id, name)} alt={alt ?? ""} />;
                },
                table: ({ children }) => (
                  <div className="md-table">
                    <table>{children}</table>
                  </div>
                ),
                a: ({ href, children }) => (
                  <a href={href} target="_blank" rel="noreferrer">
                    {children}
                  </a>
                ),
              }}
            >
              {data.markdown}
            </ReactMarkdown>
          </div>
        )}
      </article>
    </div>
  );
}
