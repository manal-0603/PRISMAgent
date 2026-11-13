"use client";

import useSWR from "swr";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Download } from "lucide-react";
import { fetcher, fileUrl, type Run } from "@/lib/api";
import { Empty } from "../ui";

const DOWNLOADS = [
  { file: "report.docx", label: "Word" },
  { file: "report.md", label: "Markdown" },
  { file: "references.bib", label: "BibTeX" },
  { file: "evidence_table.csv", label: "Evidence table" },
];

export function ReportTab({ run }: { run: Run }) {
  const { data, error } = useSWR<{ markdown: string }>(run.report ? `/api/runs/${run.id}/report?v=${run.report.words}` : null, fetcher);
  if (!run.report) return <Empty>The manuscript appears here once the Writing agent has produced a draft.</Empty>;

  return (
    <div className="stack">
      <div className="toolbar" style={{ marginBottom: 0 }}>
        <span className="muted" style={{ fontSize: 13 }}>
          {run.report.words.toLocaleString("en-GB")} words · {run.report.final ? "final version" : "draft under review"}
        </span>
        <div className="badges">
          {DOWNLOADS.filter((d) => run.files.includes(d.file)).map((d) => (
            <a key={d.file} className="btn sm" href={fileUrl(run.id, d.file)} download>
              <Download size={13} /> {d.label}
            </a>
          ))}
        </div>
      </div>
      <article className="paper">
        {error && <p className="muted">The manuscript could not be loaded.</p>}
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
